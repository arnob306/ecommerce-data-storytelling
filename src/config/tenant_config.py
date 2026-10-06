"""
TenantConfig - centralised path and config resolution for all pipeline components.

Designed for single-tenant use now, multi-tenant ready for later.

Single tenant (current usage):
    config = TenantConfig()
    config.narratives_path       # data/insights/narratives.json
    config.monitoring_log_path   # data/monitoring/llm_calls.jsonl
    config.vector_store_path     # data/vector_store

Multi-tenant (future):
    config = TenantConfig(tenant_id='acme_retail')
    config.narratives_path       # data/tenants/acme_retail/insights/narratives.json
    config.monitoring_log_path   # data/tenants/acme_retail/monitoring/llm_calls.jsonl
    config.vector_store_path     # data/tenants/acme_retail/vector_store

The same dashboard, pipeline, and AI layer work unchanged.
Only the config object changes — no code paths branch on tenant_id.

Design decision:
    All paths are properties so they're computed lazily and can never
    be accidentally hardcoded elsewhere. Any file access in the pipeline
    should go through a TenantConfig instance, not a raw Path literal.
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import re
import yaml
import logging

logger = logging.getLogger(__name__)

# Default single-tenant base paths (current structure)
DEFAULT_DATA_ROOT = Path('data')
DEFAULT_CONFIG_ROOT = Path('config')

# tenant_id is used directly in filesystem paths and Chroma collection names,
# so it must be a safe bareword — no path separators or traversal sequences.
_TENANT_ID_RE = re.compile(r'^[A-Za-z0-9_-]+$')


@dataclass
class TenantConfig:
    """
    Resolves all file paths and config for a given tenant.

    tenant_id=None means single-tenant mode — uses existing flat
    data/ structure with no changes to current behaviour.
    """
    tenant_id: Optional[str] = None
    data_root: Path = field(default_factory=lambda: DEFAULT_DATA_ROOT)
    config_root: Path = field(default_factory=lambda: DEFAULT_CONFIG_ROOT)

    def __post_init__(self):
        self.data_root = Path(self.data_root)
        self.config_root = Path(self.config_root)
        if self.tenant_id is not None and not _TENANT_ID_RE.match(self.tenant_id):
            raise ValueError(
                f"Invalid tenant_id: {self.tenant_id!r}. "
                "Must contain only letters, digits, underscores, and hyphens."
            )

    @property
    def is_multi_tenant(self) -> bool:
        return self.tenant_id is not None

    @property
    def tenant_data_root(self) -> Path:
        """Root data directory for this tenant."""
        if self.is_multi_tenant:
            return self.data_root / 'tenants' / self.tenant_id
        return self.data_root

    # --- Cache paths ---

    @property
    def cache_dir(self) -> Path:
        return self.tenant_data_root / 'cache'

    @property
    def kpi_timeseries_path(self) -> Path:
        return self.cache_dir / 'kpi_timeseries.parquet'

    @property
    def kpi_latest_path(self) -> Path:
        return self.cache_dir / 'kpi_latest.parquet'

    @property
    def anomalies_cache_path(self) -> Path:
        return self.cache_dir / 'anomalies.parquet'

    @property
    def root_causes_cache_path(self) -> Path:
        return self.cache_dir / 'root_causes.parquet'

    # --- Insights paths ---

    @property
    def insights_dir(self) -> Path:
        return self.tenant_data_root / 'insights'

    @property
    def anomalies_path(self) -> Path:
        return self.insights_dir / 'anomalies.csv'

    @property
    def root_causes_path(self) -> Path:
        return self.insights_dir / 'root_causes.csv'

    @property
    def narratives_path(self) -> Path:
        return self.insights_dir / 'narratives.json'

    @property
    def rag_narratives_path(self) -> Path:
        return self.insights_dir / 'rag_narratives.json'

    # --- Monitoring paths ---

    @property
    def monitoring_dir(self) -> Path:
        return self.tenant_data_root / 'monitoring'

    @property
    def monitoring_log_path(self) -> Path:
        return self.monitoring_dir / 'llm_calls.jsonl'

    # --- Vector store path ---

    @property
    def vector_store_path(self) -> Path:
        return self.tenant_data_root / 'vector_store'

    @property
    def chroma_collection_name(self) -> str:
        """
        ChromaDB collection name scoped to tenant.
        Single-tenant uses 'anomalies', multi-tenant uses 'anomalies_acme_retail'.
        """
        if self.is_multi_tenant:
            return f'anomalies_{self.tenant_id}'
        return 'anomalies'

    # --- Config paths ---

    @property
    def kpis_config_path(self) -> Path:
        """
        Tenant-specific KPI config if it exists, otherwise global config.
        Allows tenants to define custom KPIs while sharing defaults.
        """
        if self.is_multi_tenant:
            tenant_config = (
                self.config_root / 'tenants' / self.tenant_id / 'kpis.yaml'
            )
            if tenant_config.exists():
                return tenant_config
        return self.config_root / 'kpis.yaml'

    @property
    def prompts_config_path(self) -> Path:
        """
        Tenant-specific prompts if they exist, otherwise global prompts.
        Allows tenants to customise tone and terminology later.
        """
        if self.is_multi_tenant:
            tenant_prompts = (
                self.config_root / 'tenants' / self.tenant_id / 'prompts.yaml'
            )
            if tenant_prompts.exists():
                return tenant_prompts
        return self.config_root / 'prompts.yaml'

    # --- Raw data path ---

    @property
    def raw_data_dir(self) -> Path:
        return self.tenant_data_root / 'raw'

    # --- Utility ---

    def ensure_dirs(self):
        """Create all required directories for this tenant."""
        dirs = [
            self.cache_dir,
            self.insights_dir,
            self.monitoring_dir,
            self.vector_store_path,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
        logger.info(
            f'Directories ready for tenant: {self.tenant_id or "default"}'
        )

    def load_prompts(self) -> dict:
        """Load prompt config for this tenant."""
        path = self.prompts_config_path
        if not path.exists():
            return {}
        with open(path) as f:
            return yaml.safe_load(f)

    def summary(self) -> dict:
        """Return a summary dict for display in the dashboard."""
        return {
            'tenant_id': self.tenant_id or 'default',
            'mode': 'multi-tenant' if self.is_multi_tenant else 'single-tenant',
            'data_root': str(self.tenant_data_root),
            'narratives': str(self.narratives_path),
            'rag_narratives': str(self.rag_narratives_path),
            'monitoring_log': str(self.monitoring_log_path),
            'vector_store': str(self.vector_store_path),
            'chroma_collection': self.chroma_collection_name,
        }


# Default single-tenant config instance
# Import this anywhere in the codebase for zero-config usage
default_config = TenantConfig()


if __name__ == '__main__':
    print('=== Single-tenant mode ===')
    cfg = TenantConfig()
    for k, v in cfg.summary().items():
        print(f'  {k}: {v}')

    print()
    print('=== Multi-tenant mode (acme_retail) ===')
    cfg_mt = TenantConfig(tenant_id='acme_retail')
    for k, v in cfg_mt.summary().items():
        print(f'  {k}: {v}')