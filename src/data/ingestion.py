"""
Data ingestion module for loading UK retail transaction data.

This module handles reading CSV files and performing initial data type conversions.
Validation happens in a separate module to keep concerns separated.
"""

import pandas as pd
from pathlib import Path
from typing import Optional
import logging


logger = logging.getLogger(__name__)


class DataLoader:
    """Loads retail transaction data from CSV files."""
    
    def __init__(self, data_dir: str = "data/raw"):
        """
        Initialise the data loader.

        """
        self.data_dir = Path(data_dir)
        if not self.data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {data_dir}")
    
    def load_retail_data(self, filename: str = "UK retail data.csv") -> pd.DataFrame:
        """
        Load UK retail transaction data from CSV.
        
        """
        filepath = self.data_dir / filename
        
        if not filepath.exists():
            raise FileNotFoundError(f"Data file not found: {filepath}")
        
        logger.info(f"Loading data from {filepath}")
        
        try:
            df = pd.read_csv(
                filepath,
                encoding='latin-1',  #to deal with special characters 
                parse_dates=['InvoiceDate'],  
                dtype={
                    'InvoiceNo': str,
                    'StockCode': str,
                    'Description': str,
                    'CustomerID': str,  # keep as string to preserve format
                    'Country': str
                }
            )
            
            logger.info(f"Loaded {len(df):,} rows and {len(df.columns)} columns")
            logger.info(f"Date range: {df['InvoiceDate'].min()} to {df['InvoiceDate'].max()}")
            
            return df
            
        except pd.errors.EmptyDataError:
            logger.error(f"File is empty: {filepath}")
            raise
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            raise
    
    def get_data_summary(self, df: pd.DataFrame) -> dict:
        """
        Get basic summary statistics about the loaded data.
        
        """
        summary = {
            'total_rows': len(df),
            'total_columns': len(df.columns),
            'date_range': {
                'start': df['InvoiceDate'].min(),
                'end': df['InvoiceDate'].max()
            },
            'unique_invoices': df['InvoiceNo'].nunique(),
            'unique_customers': df['CustomerID'].nunique(),
            'unique_products': df['StockCode'].nunique(),
            'unique_countries': df['Country'].nunique(),
            'missing_values': df.isnull().sum().to_dict(),
            'memory_usage_mb': df.memory_usage(deep=True).sum() / 1024**2
        }
        
        return summary
    
    def save_processed_data(
        self, 
        df: pd.DataFrame, 
        filename: str,
        output_dir: str = "data/processed"
    ) -> None:
        """
        Save processed data to CSV.
        
        Args:
            df: DataFrame to save
            filename: Output filename
            output_dir: Directory to save to
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        filepath = output_path / filename
        
        logger.info(f"Saving processed data to {filepath}")
        df.to_csv(filepath, index=False)
        logger.info(f"Saved {len(df):,} rows")


def load_data(filename: str = "UK retail data.csv") -> pd.DataFrame:
    """
    Convenience function to load retail data.
    
    This is a simpler interface for quick loading without instantiating the class.
    
    Args:
        filename: Name of the CSV file
        
    Returns:
        DataFrame with transaction data
    """
    loader = DataLoader()
    return loader.load_retail_data(filename)


# Example usage 
if __name__ == "__main__":
    loader = DataLoader()
    df = loader.load_retail_data()
    print("DATA LOADING SUMMARY")
    
    summary = loader.get_data_summary(df)
    
    print(f"\nTotal rows: {summary['total_rows']:,}")
    print(f"Total columns: {summary['total_columns']}")
    print(f"\nDate range: {summary['date_range']['start']} to {summary['date_range']['end']}")
    print(f"\nUnique values:")
    print(f"  - Invoices: {summary['unique_invoices']:,}")
    print(f"  - Customers: {summary['unique_customers']:,}")
    print(f"  - Products: {summary['unique_products']:,}")
    print(f"  - Countries: {summary['unique_countries']}")
    
    print(f"\nMissing values:")
    for col, count in summary['missing_values'].items():
        if count > 0:
            pct = (count / summary['total_rows']) * 100
            print(f"  - {col}: {count:,} ({pct:.1f}%)")
    
    print(f"\nMemory usage: {summary['memory_usage_mb']:.2f} MB")
    
    print("\n" + "="*50)
    print(f"\nFirst 5 rows:")
    print(df.head())