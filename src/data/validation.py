"""
Data validation module for checking data quality against contracts.

This module validates data against the rules defined in config/data_contracts.yaml
and generates quality reports.
"""

import pandas as pd
import yaml
from pathlib import Path
from typing import Dict, List, Tuple
import logging
from src.data.ingestion import DataLoader  

logger = logging.getLogger(__name__)


class DataValidator:
    """Validates data against defined contracts and quality rules."""
    
    def __init__(self, contracts_path: str = "config/data_contracts.yaml"):
        """
        Initialise validator with data contracts.
        
        """
        self.contracts_path = Path(contracts_path)
        self.contracts = self._load_contracts()
    
    def _load_contracts(self) -> dict:
        """Load data contracts from YAML file."""
        if not self.contracts_path.exists():
            raise FileNotFoundError(f"Contracts file not found: {self.contracts_path}")
        
        with open(self.contracts_path, "r") as f:
            contracts = yaml.safe_load(f)
        
        logger.info(f"Loaded data contracts from {self.contracts_path}")
        return contracts
    
    def validate_schema(self, df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """
        Validate that DataFrame has expected columns and types.
        
        """
        errors = []
        schema = self.contracts["raw_data"]["schema"]
        
        expected_cols = set(schema.keys())
        actual_cols = set(df.columns)
        
        missing_cols = expected_cols - actual_cols
        if missing_cols:
            errors.append(f"Missing columns: {missing_cols}")
        
        extra_cols = actual_cols - expected_cols
        if extra_cols:
            logger.warning(f"Extra columns found (not in schema): {extra_cols}")
        
        for col in expected_cols.intersection(actual_cols):
            expected_type = schema[col]["type"]
            actual_dtype = df[col].dtype
            
            if not self._check_dtype(actual_dtype, expected_type):
                errors.append(
                    f"Column '{col}': expected {expected_type}, got {actual_dtype}"
                )
        
        return len(errors) == 0, errors
    
    def _check_dtype(self, actual_dtype, expected_type: str) -> bool:
        """Check if actual dtype matches expected type."""
        dtype_str = str(actual_dtype).lower()
        
        if expected_type == "string":
            return dtype_str == "object"
        elif expected_type == "integer":
            return "int" in dtype_str
        elif expected_type == "float":
            return "float" in dtype_str
        elif expected_type == "datetime":
            return "datetime" in dtype_str
        else:
            return True
    
    def check_completeness(self, df: pd.DataFrame) -> Dict[str, dict]:
        """Check data completeness against thresholds."""
        results = {}
        quality_rules = self.contracts["data_quality"]["completeness"]
        
        for col, rules in quality_rules.items():
            if col not in df.columns:
                continue
            
            missing_count = df[col].isnull().sum()
            missing_pct = missing_count / len(df)
            threshold = rules["missing_threshold"]
            
            results[col] = {
                "missing_count": int(missing_count),
                "missing_percentage": float(missing_pct),
                "threshold": threshold,
                "passes": missing_pct <= threshold,
                "severity": "FAIL" if missing_pct > threshold else "PASS",
            }
        
        return results
    
    def check_value_ranges(self, df: pd.DataFrame) -> Dict[str, dict]:
        """Check if numeric values are within expected ranges."""
        results = {}
        schema = self.contracts["raw_data"]["schema"]
        
        for col, rules in schema.items():
            if col not in df.columns:
                continue
            
            validation = rules.get("validation", {})
            if "min_value" in validation or "max_value" in validation:
                min_val = validation.get("min_value")
                max_val = validation.get("max_value")
                
                violations = 0
                if min_val is not None:
                    violations += (df[col] < min_val).sum()
                if max_val is not None:
                    violations += (df[col] > max_val).sum()
                
                results[col] = {
                    "violations": int(violations),
                    "violation_percentage": float(violations / len(df)),
                    "min_value": min_val,
                    "max_value": max_val,
                    "actual_min": float(df[col].min())
                    if pd.api.types.is_numeric_dtype(df[col])
                    else None,
                    "actual_max": float(df[col].max())
                    if pd.api.types.is_numeric_dtype(df[col])
                    else None,
                    "passes": violations == 0,
                }
        
        return results
    
    def check_consistency(self, df: pd.DataFrame) -> Dict[str, dict]:
        """Check business logic consistency rules."""
        results = {}
        rules = self.contracts["data_quality"]["consistency"]["rules"]
        
        for rule in rules:
            name = rule["name"]
            description = rule["description"]
            
            if name == "cancellation_quantity_match":
                cancellations = df[df["InvoiceNo"].str.startswith("C", na=False)]
                violations = (cancellations["Quantity"] > 0).sum()
                
                results[name] = {
                    "description": description,
                    "violations": int(violations),
                    "total_checked": len(cancellations),
                    "passes": violations == 0,
                }
            
            elif name == "positive_price":
                violations = (df["UnitPrice"] < 0).sum()
                
                results[name] = {
                    "description": description,
                    "violations": int(violations),
                    "total_checked": len(df),
                    "passes": violations == 0,
                }
            
            elif name == "valid_transaction_value":
                transaction_value = df["Quantity"] * df["UnitPrice"]
                violations = (transaction_value.abs() > 100000).sum()
                
                results[name] = {
                    "description": description,
                    "violations": int(violations),
                    "total_checked": len(df),
                    "passes": violations == 0,
                }
        
        return results
    
    def generate_quality_report(self, df: pd.DataFrame) -> dict:
        """Generate comprehensive data quality report."""
        logger.info("Generating data quality report...")
        
        schema_valid, schema_errors = self.validate_schema(df)
        completeness = self.check_completeness(df)
        ranges = self.check_value_ranges(df)
        consistency = self.check_consistency(df)
        
        total = passed = 0
        
        total += 1
        passed += int(schema_valid)
        
        for r in completeness.values():
            total += 1
            passed += int(r["passes"])
        
        for r in ranges.values():
            total += 1
            passed += int(r["passes"])
        
        for r in consistency.values():
            total += 1
            passed += int(r["passes"])
        
        score = passed / total if total else 0
        
        report = {
            "overall_quality_score": score,
            "total_checks": total,
            "passed_checks": passed,
            "failed_checks": total - passed,
            "schema_validation": {
                "is_valid": schema_valid,
                "errors": schema_errors,
            },
            "completeness": completeness,
            "value_ranges": ranges,
            "consistency": consistency,
            "recommendation": self._get_recommendation(score),
        }
        
        logger.info(f"Quality score: {score:.2%}")
        return report
    
    def _get_recommendation(self, score: float) -> str:
        threshold = self.contracts["validation_thresholds"]["overall_quality_score"][
            "minimum"
        ]
        
        if score >= threshold:
            return "PASS: Data quality meets requirements. Safe to proceed with analysis."
        return (
            f"FAIL: Data quality below threshold "
            f"({score:.2%} < {threshold:.2%}). Review and fix issues."
        )
    
    def print_report(self, report: dict) -> None:
        """Print quality report in readable format."""
        print("\n" + "=" * 60)
        print("DATA QUALITY REPORT")
        print("=" * 60)
        
        print(f"\nOverall Quality Score: {report['overall_quality_score']:.2%}")
        print(f"Checks: {report['passed_checks']}/{report['total_checks']} passed")
        print(f"\nRecommendation: {report['recommendation']}")
        
        print("\n" + "-" * 60)
        print("SCHEMA VALIDATION")
        print("-" * 60)
        if report["schema_validation"]["is_valid"]:
            print("PASS: Schema is valid")
        else:
            for e in report["schema_validation"]["errors"]:
                print(f"FAIL: {e}")

        print("\n" + "-" * 60)
        print("COMPLETENESS CHECKS")
        print("-" * 60)
        for col, r in report["completeness"].items():
            status = "PASS" if r["passes"] else "FAIL"
            print(
                f"{status} {col}: {r['missing_percentage']:.1%} "
                f"(threshold: {r['threshold']:.1%})"
            )

        print("\n" + "-" * 60)
        print("CONSISTENCY CHECKS")
        print("-" * 60)
        for name, r in report["consistency"].items():
            status = "PASS" if r["passes"] else "FAIL"
            print(f"{status} {name}: {r['violations']} violations")
            print(f"  {r['description']}")
        
        print("\n" + "=" * 60)


def main():
    loader = DataLoader()
    df = loader.load_retail_data()
    
    validator = DataValidator()
    report = validator.generate_quality_report(df)
    validator.print_report(report)


if __name__ == "__main__":
    main()
