"""
RAG Narrative Generator - context-aware LLM narratives using LangChain + ChromaDB.

Replaces the direct Groq API call in narrator.py with a full RAG pipeline:
  1. Retrieve 3 most similar historical anomalies from ChromaDB
  2. Inject retrieved context into the prompt via LangChain
  3. Generate narrative with Groq (Llama 3.1-8b-instant)
  4. Log call via monitoring layer

The result is narratives that reference historical patterns rather than
treating each anomaly in isolation. For example, a November revenue spike
narrative can now reference the September spike from the same year.

Design decisions:
  - LangChain PromptTemplate rather than f-string prompt building.
    Reason: LangChain is explicitly on the target skills list and
    interviewers recognise the pattern. Functionally equivalent to
    f-strings but demonstrates the framework.

  - LangChain LCEL (pipe syntax: prompt | llm | parser) for the chain.
    Reason: this is the current LangChain standard. Older chain classes
    (LLMChain, ConversationalChain) are being deprecated.

  - Same monitoring layer as narrator.py.
    Reason: RAG calls should be comparable to non-RAG calls in the
    monitoring log. prompt_version field distinguishes them (e.g. 'v2-rag').

  - Results saved to a separate file: data/insights/rag_narratives.json.
    Reason: keeps RAG and non-RAG outputs separate for comparison.
    The dashboard can choose which to display.

Usage:
    python -m src.narratives.rag_narrator

Requires:
    GROQ_API_KEY in .env
    Vector store built: python -m src.narratives.retriever
"""

import json
import os
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

from src.narratives.monitor import LLMMonitor
from src.narratives.retriever import AnomalyRetriever

load_dotenv()
logger = logging.getLogger(__name__)

RAG_NARRATIVES_PATH = Path('data/insights/rag_narratives.json')
CACHE_DIR = Path('data/cache')
MODEL = 'allam-2-7b'

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

# LangChain PromptTemplate for RAG narrative generation
# {context} is injected by the retriever at runtime
RAG_PROMPT_TEMPLATE = PromptTemplate.from_template("""
You are a senior data analyst writing a concise briefing for a non-technical business executive.

{context}

Current anomaly to explain:
- Metric: {kpi}
- Date: {date}
- Severity: {severity}
- The metric was {deviation_pct:.1f}% {direction} expected
- Top dimensional drivers: {drivers_text}

Write exactly 2 sentences. First sentence: what happened and which segment drove it, \
in plain language. Second sentence: what this likely means for the business, \
referencing any relevant historical pattern from the context above if applicable.
Do not use jargon, percentages, or statistical terms. Do not start with "I". \
Write in third person past tense.
""")


def build_rag_chain(llm: ChatGroq):
    """
    Build a LangChain LCEL chain: prompt | llm.

    Deliberately stops at the raw AIMessage rather than piping through
    StrOutputParser - the message's response metadata carries the real
    token usage, which is needed for accurate cost/observability tracking
    and would otherwise be lost once the message is reduced to a string.
    """
    return RAG_PROMPT_TEMPLATE | llm


def build_prompt_inputs(row: pd.Series, context: str) -> dict:
    """Build the input dict for the LangChain PromptTemplate."""
    kpi = KPI_DISPLAY_NAMES.get(row['kpi_name'], row['kpi_name'])
    date = pd.Timestamp(row['date']).strftime('%B %d, %Y')
    direction = 'above' if row.get('total_deviation', 0) > 0 else 'below'
    deviation_pct = abs(row.get('total_deviation_pct', 0))

    drivers = []
    for i in range(1, 4):
        dim_col = f'driver_{i}_dimension'
        seg_col = f'driver_{i}_segment'
        if dim_col in row and pd.notna(row.get(dim_col)):
            drivers.append(f"{row[dim_col]} = {row[seg_col]}")

    drivers_text = ', '.join(drivers) if drivers else 'no specific segment identified'

    return {
        'context': context,
        'kpi': kpi,
        'date': date,
        'severity': row['anomaly_severity'].upper(),
        'deviation_pct': deviation_pct,
        'direction': direction,
        'drivers_text': drivers_text,
    }


def run_rag_narrator(force_regenerate: bool = False):
    """
    Generate RAG-enhanced narratives for all explained anomalies.

    Pipeline per anomaly:
        1. Retrieve 3 similar past anomalies from ChromaDB
        2. Format retrieved docs as context block
        3. Build LangChain prompt with context injected
        4. Invoke chain (Groq API call)
        5. Log via monitoring layer
        6. Cache result to rag_narratives.json
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s:%(name)s:%(message)s'
    )

    api_key = os.getenv('GROQ_API_KEY')
    if not api_key:
        print('ERROR: GROQ_API_KEY not found in .env file.')
        return

    # Initialise LangChain LLM
    llm = ChatGroq(
        api_key=api_key,
        model=MODEL,
        temperature=0.3,
        max_tokens=200,
        timeout=30,
        max_retries=2,
    )

    # Build LangChain LCEL chain
    chain = build_rag_chain(llm)

    # Initialise retriever and ensure vector store is built
    retriever = AnomalyRetriever()
    doc_count = retriever.build()
    logger.info(f'Vector store ready: {doc_count} documents')

    # Initialise monitor
    monitor = LLMMonitor()

    # Load root causes
    rc_path = CACHE_DIR / 'root_causes.parquet'
    if not rc_path.exists():
        rc_path = Path('data/insights/root_causes.csv')
        if not rc_path.exists():
            print('ERROR: root_causes not found. Run Phase 5 first.')
            return
        rc_df = pd.read_csv(rc_path)
    else:
        rc_df = pd.read_parquet(rc_path)

    explained = rc_df[rc_df['status'] == 'analysed'].copy()
    logger.info(f'Generating RAG narratives for {len(explained)} anomalies')

    # Load existing RAG narratives
    existing = {}
    if RAG_NARRATIVES_PATH.exists() and not force_regenerate:
        with open(RAG_NARRATIVES_PATH) as f:
            existing = json.load(f)
        logger.info(f'Loaded {len(existing)} existing RAG narratives')

    narratives = dict(existing)
    generated_count = 0
    skipped_count = 0

    for _, row in explained.iterrows():
        key = f"{row['kpi_name']}_{pd.Timestamp(row['date']).strftime('%Y-%m-%d')}"

        if key in narratives and not force_regenerate:
            skipped_count += 1
            continue

        try:
            # Step 1: Retrieve similar historical anomalies, anchored to this
            # anomaly's own severity/direction/magnitude (not just its KPI)
            similar = retriever.retrieve(
                kpi_name=row['kpi_name'],
                exclude_date=str(row['date']),
                n=3,
                same_kpi_only=True,
                severity=row.get('anomaly_severity'),
                direction='above' if row.get('total_deviation', 0) > 0 else 'below',
                deviation_pct=abs(row.get('total_deviation_pct', 0))
            )
            context = retriever.format_context(similar)

            # Step 2: Build prompt inputs
            prompt_inputs = build_prompt_inputs(row, context)

            # Step 3: Invoke chain with monitoring
            with monitor.track(
                prompt_version='v2-rag',
                model=MODEL,
                kpi_name=row['kpi_name'],
                anomaly_date=str(row['date'])
            ) as call:
                # LangChain LCEL chain invocation - keep the raw AIMessage
                # (rather than piping through StrOutputParser) so real token
                # usage can be read from its response metadata.
                ai_message = chain.invoke(prompt_inputs)
                output_text = ai_message.content
                monitor.record_response(call, _usage_from_message(ai_message), output_text)

            narratives[key] = {
                'kpi_name': row['kpi_name'],
                'date': str(row['date']),
                'severity': row['anomaly_severity'],
                'narrative': output_text.strip(),
                'retrieved_context': [s['id'] for s in similar],
                'prompt_version': 'v2-rag',
                'generated_at': datetime.now().isoformat()
            }
            generated_count += 1
            logger.info(f'Generated RAG narrative for {key}')

        except Exception as e:
            logger.error(f'Failed RAG narrative for {key}: {e}')
            narratives[key] = {
                'kpi_name': row['kpi_name'],
                'date': str(row['date']),
                'severity': row['anomaly_severity'],
                'narrative': f'RAG narrative generation failed: {e}',
                'retrieved_context': [],
                'prompt_version': 'v2-rag',
                'generated_at': datetime.now().isoformat()
            }

    RAG_NARRATIVES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RAG_NARRATIVES_PATH, 'w') as f:
        json.dump(narratives, f, indent=2)

    print(f'\nRAG narrative generation complete:')
    print(f'  Generated: {generated_count}')
    print(f'  Skipped (cached): {skipped_count}')
    print(f'  Total: {len(narratives)}')
    print(f'  Saved to: {RAG_NARRATIVES_PATH}')

    monitor.print_summary()


def _usage_from_message(message) -> object:
    """
    Extract real token usage from a LangChain AIMessage and wrap it in the
    Groq-style `response.usage.*` shape that monitor.record_response expects.

    ChatGroq populates both `usage_metadata` (LangChain's standardised field)
    and `response_metadata['token_usage']` (the raw Groq/OpenAI-style dict);
    either can be present depending on langchain-groq version, so both are
    checked.
    """
    usage_metadata = getattr(message, 'usage_metadata', None) or {}
    token_usage = getattr(message, 'response_metadata', {}).get('token_usage', {}) or {}

    prompt_tokens = usage_metadata.get('input_tokens', token_usage.get('prompt_tokens', 0))
    completion_tokens = usage_metadata.get('output_tokens', token_usage.get('completion_tokens', 0))
    total_tokens = usage_metadata.get(
        'total_tokens', token_usage.get('total_tokens', prompt_tokens + completion_tokens)
    )

    class Usage:
        pass
    class Response:
        pass

    usage = Usage()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = total_tokens

    response = Response()
    response.usage = usage
    return response


def load_rag_narratives() -> dict:
    """Load cached RAG narratives. Returns empty dict if not yet generated."""
    if not RAG_NARRATIVES_PATH.exists():
        return {}
    with open(RAG_NARRATIVES_PATH) as f:
        return json.load(f)


if __name__ == '__main__':
    run_rag_narrator()