"""
RAG Retriever - vector store and similarity search for anomaly context.

Builds a ChromaDB collection from historical anomalies and root causes.
When generating a narrative for a new anomaly, the retriever finds the
3 most similar past anomalies and returns them as context for the LLM.

Design decisions:
  - ChromaDB local persistence rather than hosted vector store (Pinecone etc).
    Reason: no API key, no cost, no external dependency. Architecture pattern
    is identical - swapping ChromaDB for Pinecone is one line of code.

  - sentence-transformers for embeddings rather than OpenAI embeddings API.
    Reason: free, runs on CPU, fast enough for 47 documents. For this scale
    the quality difference vs OpenAI embeddings is negligible.

  - Documents are built from structured anomaly data, not raw text.
    Reason: the structured fields (KPI, severity, drivers, date, deviation)
    contain all the signal needed for similarity search. Free-text descriptions
    would require the LLM to parse them before embedding.

  - Retrieval is by KPI + semantic similarity combined.
    Reason: a revenue anomaly should retrieve revenue anomalies first.
    Pure semantic search without KPI filtering would match structurally similar
    anomalies across different metrics, which is less useful for narrative context.

Usage:
    from src.narratives.retriever import AnomalyRetriever
    retriever = AnomalyRetriever()
    retriever.build()  # run once to embed all documents
    similar = retriever.retrieve('total_revenue', '2011-11-20', n=3)
"""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

CACHE_DIR = Path('data/cache')
CHROMA_DIR = Path('data/vector_store')

# sentence-transformers model - small, fast, free, runs on CPU
EMBEDDING_MODEL = 'all-MiniLM-L6-v2'

KPI_DISPLAY_NAMES = {
    'total_revenue': 'Total Revenue',
    'order_count': 'Order Count',
    'units_sold': 'Units Sold',
    'active_customers': 'Active Customers',
    'revenue_per_order': 'Revenue per Order',
    'revenue_per_customer': 'Revenue per Customer',
    'items_per_order': 'Items per Order',
    'avg_unit_price': 'Average Unit Price',
    'repeat_customer_rate': 'Repeat Customer Rate',
    'product_revenue_concentration': 'Product Revenue Concentration',
    'product_return_rate': 'Product Return Rate',
    'international_revenue_share': 'International Revenue Share',
    'weekend_revenue_share': 'Weekend Revenue Share',
    'peak_hour_concentration': 'Peak Hour Concentration',
}


def build_document(row: pd.Series) -> str:
    """
    Convert a root cause result row into a text document for embedding.

    Structured format ensures consistent signal across all documents.
    The embedding model learns similarity from the text content, so
    consistent field naming matters more than natural language fluency.
    """
    kpi = KPI_DISPLAY_NAMES.get(row['kpi_name'], row['kpi_name'])
    date = pd.Timestamp(row['date']).strftime('%B %Y')
    direction = 'above' if row.get('total_deviation', 0) > 0 else 'below'
    deviation_pct = abs(row.get('total_deviation_pct', 0))
    severity = row.get('anomaly_severity', 'unknown')
    status = row.get('status', 'unknown')

    # Build driver text
    drivers = []
    for i in range(1, 4):
        dim_col = f'driver_{i}_dimension'
        seg_col = f'driver_{i}_segment'
        if dim_col in row and pd.notna(row.get(dim_col)):
            drivers.append(f"{row[dim_col]} = {row[seg_col]}")

    drivers_text = ', '.join(drivers) if drivers else 'no drivers identified'

    doc = (
        f"KPI: {kpi}. "
        f"Date: {date}. "
        f"Severity: {severity}. "
        f"The metric was {deviation_pct:.1f}% {direction} expected. "
        f"Status: {status}. "
        f"Top drivers: {drivers_text}."
    )

    return doc


class AnomalyRetriever:
    """
    Builds and queries a vector store of historical anomaly documents.

    Workflow:
        1. Call build() once to embed all root cause documents
        2. Call retrieve(kpi_name, date, n) to get similar past anomalies
        3. Use the returned context in the LLM prompt

    The vector store persists to data/vector_store/ so build() only
    needs to run once unless the underlying data changes.
    """

    def __init__(self):
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)

        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )

        self.client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self.collection = self.client.get_or_create_collection(
            name='anomalies',
            embedding_function=self.embedding_fn,
            metadata={'hnsw:space': 'cosine'}
        )

    def build(self, force_rebuild: bool = False) -> int:
        """
        Embed all root cause documents into the vector store.

        Skips if collection already has documents unless force_rebuild=True.
        Returns the number of documents in the collection after building.
        """
        existing_count = self.collection.count()

        if existing_count > 0 and not force_rebuild:
            logger.info(
                f'Vector store already has {existing_count} documents. '
                f'Skipping build. Use force_rebuild=True to regenerate.'
            )
            return existing_count

        if force_rebuild and existing_count > 0:
            logger.info('Force rebuild - deleting existing collection')
            self.client.delete_collection('anomalies')
            self.collection = self.client.get_or_create_collection(
                name='anomalies',
                embedding_function=self.embedding_fn,
                metadata={'hnsw:space': 'cosine'}
            )

        # Load root causes
        rc_path = CACHE_DIR / 'root_causes.parquet'
        if not rc_path.exists():
            rc_path = Path('data/insights/root_causes.csv')
            if not rc_path.exists():
                raise FileNotFoundError(
                    'root_causes not found. Run Phase 5 first.'
                )
            rc_df = pd.read_csv(rc_path)
        else:
            rc_df = pd.read_parquet(rc_path)

        logger.info(f'Building vector store from {len(rc_df)} anomaly records...')

        documents = []
        metadatas = []
        ids = []

        for _, row in rc_df.iterrows():
            doc_id = (
                f"{row['kpi_name']}_"
                f"{pd.Timestamp(row['date']).strftime('%Y-%m-%d')}"
            )
            doc_text = build_document(row)

            documents.append(doc_text)
            metadatas.append({
                'kpi_name': str(row['kpi_name']),
                'date': str(row['date']),
                'severity': str(row.get('anomaly_severity', 'unknown')),
                'status': str(row.get('status', 'unknown')),
                'direction': 'above' if row.get('total_deviation', 0) > 0 else 'below',
            })
            ids.append(doc_id)

        self.collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )

        count = self.collection.count()
        logger.info(f'Vector store built: {count} documents embedded')
        return count

    def retrieve(
        self,
        kpi_name: str,
        exclude_date: str,
        n: int = 3,
        same_kpi_only: bool = False,
        severity: Optional[str] = None,
        direction: Optional[str] = None,
        deviation_pct: Optional[float] = None,
        max_distance: Optional[float] = 0.6
    ) -> list[dict]:
        """
        Retrieve the n most similar past anomalies to a given KPI + date.

        Args:
            kpi_name: the KPI to find similar anomalies for
            exclude_date: the current anomaly date - excluded from results
                          so the document doesn't retrieve itself
            n: number of similar anomalies to return (default 3)
            same_kpi_only: if True, only retrieve anomalies for the same KPI.
                           Default False - cross-KPI retrieval often surfaces
                           useful context (e.g. revenue and order count spikes
                           on the same date)
            severity, direction, deviation_pct: characteristics of the current
                           anomaly. Folded into the query text so the search
                           is anchored to this anomaly's actual profile rather
                           than a near-constant per-KPI string, which otherwise
                           makes "most similar" mostly a function of incidental
                           text in the stored documents.
            max_distance: results with cosine distance above this are dropped
                          rather than surfaced as if they were meaningfully
                          similar. None disables the cutoff.

        Returns:
            List of dicts with keys: document, kpi_name, date, severity, distance
        """
        if self.collection.count() == 0:
            logger.warning('Vector store is empty. Run build() first.')
            return []

        # Build a query document using the same format as the stored documents.
        # Anchoring on severity/direction/magnitude (not just KPI name) means
        # different anomalies on the same KPI produce different query
        # embeddings, so "most similar" reflects the actual anomaly profile.
        kpi_display = KPI_DISPLAY_NAMES.get(kpi_name, kpi_name)
        query_text = f"KPI: {kpi_display}."
        if severity:
            query_text += f" Severity: {severity}."
        if deviation_pct is not None and direction:
            query_text += f" The metric was {deviation_pct:.1f}% {direction} expected."
        if query_text == f"KPI: {kpi_display}.":
            query_text += " Anomaly detected."

        # Retrieve more than needed so we can filter the excluded date
        where_filter = None
        if same_kpi_only:
            where_filter = {'kpi_name': kpi_name}

        results = self.collection.query(
            query_texts=[query_text],
            n_results=min(n + 5, self.collection.count()),
            where=where_filter
        )

        # Filter out the current anomaly date, drop weak matches, and format results
        similar = []
        exclude_key = f"{kpi_name}_{pd.Timestamp(exclude_date).strftime('%Y-%m-%d')}"

        for i, doc_id in enumerate(results['ids'][0]):
            if doc_id == exclude_key:
                continue
            distance = results['distances'][0][i]
            if max_distance is not None and distance > max_distance:
                continue
            if len(similar) >= n:
                break

            similar.append({
                'id': doc_id,
                'document': results['documents'][0][i],
                'kpi_name': results['metadatas'][0][i]['kpi_name'],
                'date': results['metadatas'][0][i]['date'],
                'severity': results['metadatas'][0][i]['severity'],
                'distance': round(distance, 4)
            })

        return similar

    def format_context(self, similar: list[dict]) -> str:
        """
        Format retrieved anomalies as a readable context block for the LLM prompt.
        """
        if not similar:
            return 'No similar historical anomalies found.'

        lines = ['Similar historical anomalies for context:']
        for i, item in enumerate(similar, 1):
            date = pd.Timestamp(item['date']).strftime('%B %Y')
            lines.append(
                f"{i}. {item['kpi_name']} anomaly in {date} "
                f"(severity: {item['severity']}): {item['document']}"
            )

        return '\n'.join(lines)


if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO)

    retriever = AnomalyRetriever()
    count = retriever.build()
    print(f'\nVector store built with {count} documents')

    # Test retrieval
    print('\nTest: retrieving similar anomalies for total_revenue 2011-11-20')
    similar = retriever.retrieve('total_revenue', '2011-11-20', n=3)
    print(retriever.format_context(similar))