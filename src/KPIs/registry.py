"""
KPI Registry - manages KPI definitions from config/kpis.yaml

This module loads KPI configurations and provides convenient access
to KPI metadata, formulas, and thresholds.
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class KPIRegistry:
    """Registry for KPI definitions from YAML config."""
    
    def __init__(self, config_path: str = "config/kpis.yaml"):
        """
        Initialize KPI registry.
        
        Args:
            config_path: Path to KPI configuration YAML file
        """
        # Find project root
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent
        
        self.config_path = project_root / config_path
        self.config = self._load_config()
        self.kpis = self.config.get('kpis', {})
        
        logger.info(f"Loaded {len(self.kpis)} KPI definitions from {self.config_path}")
    
    def _load_config(self) -> dict:
        """Load KPI configuration from YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"KPI config file not found: {self.config_path}")
        
        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        return config
    
    def get_kpi(self, kpi_name: str) -> Optional[dict]:
        """
        Get KPI definition by name.
        
        Args:
            kpi_name: Name of the KPI
            
        Returns:
            KPI definition dict or None if not found
        """
        return self.kpis.get(kpi_name)
    
    def get_formula(self, kpi_name: str) -> Optional[str]:
        """Get formula for a KPI."""
        kpi = self.get_kpi(kpi_name)
        return kpi.get('formula') if kpi else None
    
    def get_owner(self, kpi_name: str) -> Optional[str]:
        """Get owner for a KPI."""
        kpi = self.get_kpi(kpi_name)
        return kpi.get('owner') if kpi else None
    
    def get_cadence(self, kpi_name: str) -> Optional[str]:
        """Get cadence (daily/weekly) for a KPI."""
        kpi = self.get_kpi(kpi_name)
        return kpi.get('cadence') if kpi else None
    
    def get_thresholds(self, kpi_name: str) -> Optional[dict]:
        """Get anomaly detection thresholds for a KPI."""
        kpi = self.get_kpi(kpi_name)
        return kpi.get('thresholds') if kpi else None
    
    def list_kpis(self) -> List[str]:
        """Get list of all KPI names."""
        return list(self.kpis.keys())
    
    def list_kpis_by_owner(self, owner: str) -> List[str]:
        """
        Get list of KPIs for a specific owner.
        
        Args:
            owner: Owner name (e.g., "Finance", "Operations")
            
        Returns:
            List of KPI names owned by this person/team
        """
        return [
            name for name, kpi in self.kpis.items()
            if kpi.get('owner') == owner
        ]
    
    def list_kpis_by_cadence(self, cadence: str) -> List[str]:
        """
        Get list of KPIs for a specific cadence.
        
        Args:
            cadence: "daily" or "weekly"
            
        Returns:
            List of KPI names with this cadence
        """
        return [
            name for name, kpi in self.kpis.items()
            if kpi.get('cadence') == cadence
        ]
    
    def get_metadata(self) -> dict:
        """Get metadata section from config."""
        return self.config.get('metadata', {})
    
    def print_summary(self):
        """Print summary of loaded KPIs."""
        print("\n" + "="*60)
        print("KPI REGISTRY SUMMARY")
        print("="*60)
        print(f"\nTotal KPIs: {len(self.kpis)}")
        
        # By owner
        owners = set(kpi.get('owner') for kpi in self.kpis.values() if kpi.get('owner'))
        print(f"\nKPIs by Owner:")
        for owner in sorted(owners):
            kpis = self.list_kpis_by_owner(owner)
            print(f"  {owner}: {len(kpis)} KPIs")
            for kpi_name in kpis:
                print(f"    - {kpi_name}")
        
        # By cadence
        print(f"\nKPIs by Cadence:")
        for cadence in ['daily', 'weekly']:
            kpis = self.list_kpis_by_cadence(cadence)
            print(f"  {cadence}: {len(kpis)} KPIs")
        
        print("\n" + "="*60)


# Example usage
if __name__ == "__main__":
    registry = KPIRegistry()
    
    # Print summary
    registry.print_summary()
    
    # Example: Get specific KPI details
    print("\n" + "="*60)
    print("EXAMPLE: Total Revenue KPI")
    print("="*60)
    
    kpi_name = "total_revenue"
    kpi = registry.get_kpi(kpi_name)
    
    if kpi:
        print(f"\nName: {kpi_name}")
        print(f"Formula: {kpi.get('formula')}")
        print(f"Owner: {kpi.get('owner')}")
        print(f"Cadence: {kpi.get('cadence')}")
        print(f"Description: {kpi.get('description')}")
        print(f"Thresholds: {kpi.get('thresholds')}")