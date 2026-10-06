"""
Formula parsing and execution for KPI calculations.

This module safely parses and executes formula strings from kpis.yaml.
Supports basic operations: sum, count, avg, min, max, arithmetic,
conditional filtering with where/with clauses, and complex aggregations.
"""

import pandas as pd
import re
from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


class FormulaParser:
    """Parses and executes formula strings safely."""
    
    ALLOWED_FUNCTIONS = {
        'sum', 'count', 'avg', 'mean', 'min', 'max',
        'distinct', 'nunique'
    }

    # Special KPI names that require multi-step calculations.
    # These cannot be expressed as simple formulas so are hardcoded here.
    SPECIAL_EXPRESSIONS = {
        'revenue_top_20_products',
        'revenue_in_top_3_hours',
    }
    
    def __init__(self, df: pd.DataFrame):
        """Initialise parser with a DataFrame."""
        self.df = df

    # =========================================================================
    # DERIVED COLUMNS
    # =========================================================================

    def _add_derived_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add derived columns needed for conditional filtering.

        Creates a working copy of the DataFrame with:
          - TransactionValue: Quantity * UnitPrice (alias for 'revenue' in formulas)
          - DayOfWeek: Day name derived from InvoiceDate (e.g. 'Saturday')
          - HourOfDay: Hour integer derived from InvoiceDate (e.g. 14)

        We work on a copy so the original DataFrame is never mutated.
        """
        df = df.copy()

        if 'TransactionValue' not in df.columns:
            df['TransactionValue'] = df['Quantity'] * df['UnitPrice']

        if 'DayOfWeek' not in df.columns:
            df['DayOfWeek'] = df['InvoiceDate'].dt.day_name()

        if 'HourOfDay' not in df.columns:
            df['HourOfDay'] = df['InvoiceDate'].dt.hour

        return df

    # =========================================================================
    # TOP-LEVEL DISPATCH
    # =========================================================================

    def parse_and_execute(self, formula: str, calculated_kpis: dict = None) -> float:
        """
        Parse and execute a formula string.

        Ratio check runs BEFORE aggregate check because some formulas like
        'sum(Quantity) / order_count' contain both a '/' and start with 'sum('.
        Checking ratio first ensures the division is not swallowed by the
        aggregate parser.
        """
        formula = formula.strip()
        logger.debug(f"Parsing formula: {formula}")

        if self._is_ratio_formula(formula):
            return self._execute_ratio(formula, calculated_kpis)
        elif self._is_aggregate_function(formula):
            return self._execute_aggregate(formula)
        else:
            raise ValueError(f"Unsupported formula pattern: {formula}")

    # =========================================================================
    # PATTERN DETECTION
    # =========================================================================

    def _is_aggregate_function(self, formula: str) -> bool:
        """Check if formula starts with a known aggregate function."""
        pattern = r'^(sum|count|avg|mean|min|max|nunique)\('
        return bool(re.match(pattern, formula, re.IGNORECASE))

    def _is_ratio_formula(self, formula: str) -> bool:
        """Check if formula is a ratio like metric1 / metric2."""
        return '/' in formula

    def _has_condition(self, args: str) -> bool:
        """Check if aggregate args contain a where/with filter clause."""
        return bool(re.search(r'\b(where|with)\b', args, re.IGNORECASE))

    def _is_customer_groupby(self, args: str) -> bool:
        """
        Check if this is a customer groupby condition.

        Detects patterns like 'CustomerID with orders > 1' where 'orders'
        is an aggregated count per customer, not a raw column.
        """
        return bool(re.search(r'CustomerID\s+with\s+orders', args, re.IGNORECASE))

    def _is_first_order_date(self, args: str) -> bool:
        """
        Check if this is a new customer formula.

        Detects 'CustomerID with first_order_date in period'.
        """
        return bool(re.search(r'first_order_date', args, re.IGNORECASE))

    # =========================================================================
    # AGGREGATE EXECUTION
    # =========================================================================

    def _execute_aggregate(self, formula: str) -> float:
        """
        Execute an aggregate function, with or without a condition.

        Examples:
            sum(Quantity * UnitPrice)
            count(distinct InvoiceNo)
            sum(revenue where Country != 'United Kingdom')
            count(InvoiceNo with Quantity < 0)
            count(distinct CustomerID with orders > 1)
        """
        match = re.match(r'(\w+)\((.*)\)$', formula, re.IGNORECASE | re.DOTALL)
        if not match:
            raise ValueError(f"Invalid aggregate formula: {formula}")

        func_name = match.group(1).lower()
        args = match.group(2).strip()

        if func_name not in self.ALLOWED_FUNCTIONS:
            raise ValueError(f"Function '{func_name}' not allowed.")

        # Route customer groupby conditions before generic conditional handling.
        # These require a groupby step, not a simple row filter.
        if self._is_customer_groupby(args):
            return self._execute_customer_groupby(args)

        if self._is_first_order_date(args):
            return self._execute_new_customers()

        if self._has_condition(args):
            return self._execute_conditional_aggregate(func_name, args)

        if 'distinct' in args.lower():
            return self._execute_distinct_count(args)
        if func_name == 'sum':
            return self._execute_sum(args)
        elif func_name in ['count', 'nunique']:
            return self._execute_count(args)
        elif func_name in ['avg', 'mean']:
            return self._execute_avg(args)
        elif func_name == 'min':
            return self._execute_min(args)
        elif func_name == 'max':
            return self._execute_max(args)
        else:
            raise ValueError(f"Unsupported function: {func_name}")

    # =========================================================================
    # CUSTOMER GROUPBY HANDLERS
    # =========================================================================

    def _execute_customer_groupby(self, args: str) -> float:
        """
        Handle 'count(distinct CustomerID with orders > 1)'.

        'orders' is not a raw column — it is the count of distinct invoices
        per customer. This requires:
          1. Group by CustomerID
          2. Count distinct InvoiceNo per customer (= order count per customer)
          3. Filter to customers where that count > 1
          4. Count those customers

        This is fundamentally different from row-level filtering, which is why
        it needs its own handler rather than going through _apply_condition.
        """
        # Parse the threshold from 'orders > N'
        threshold_match = re.search(r'orders\s*>\s*(\d+)', args, re.IGNORECASE)
        if not threshold_match:
            raise ValueError(f"Could not parse order threshold from: {args}")

        threshold = int(threshold_match.group(1))

        # Count orders per customer, then filter
        orders_per_customer = (
            self.df.groupby('CustomerID')['InvoiceNo']
            .nunique()
        )
        repeat_customers = orders_per_customer[orders_per_customer > threshold]
        return float(len(repeat_customers))

    def _execute_new_customers(self) -> float:
        """
        Handle 'count(distinct CustomerID with first_order_date in period)'.

        Since we only have one dataset (Dec 2010 - Dec 2011), every customer's
        first order falls within this period. This means new_customers will
        equal active_customers for this dataset. The calculation is still
        correct — we find each customer's earliest InvoiceDate and count
        customers whose first order falls within the dataset's date range.

        NOTE: In a production system with historical data, you would compare
        first_order_date against a separate lookup of pre-existing customers.
        """
        # Find each customer's first order date
        first_orders = (
            self.df.groupby('CustomerID')['InvoiceDate']
            .min()
        )

        # The period is the full date range of the dataset
        period_start = self.df['InvoiceDate'].min()
        period_end = self.df['InvoiceDate'].max()

        new_custs = first_orders[
            (first_orders >= period_start) & (first_orders <= period_end)
        ]
        return float(len(new_custs))

    # =========================================================================
    # SPECIAL EXPRESSION HANDLERS (top-N calculations)
    # =========================================================================

    def _compute_revenue_top_20_products(self) -> float:
        """
        Compute revenue from the top 20 products by revenue.

        Steps:
          1. Compute TransactionValue (Quantity * UnitPrice) per row
          2. Group by StockCode and sum TransactionValue
          3. Sort descending, take top 20
          4. Sum those 20 values

        This cannot be expressed as a simple formula string because it
        requires a sort + slice operation, so it is hardcoded here.
        """
        enriched = self._add_derived_columns(self.df)
        revenue_by_product = (
            enriched.groupby('StockCode')['TransactionValue']
            .sum()
            .sort_values(ascending=False)
        )
        top_20_revenue = revenue_by_product.head(20).sum()
        return float(top_20_revenue)

    def _compute_revenue_in_top_3_hours(self) -> float:
        """
        Compute revenue in the top 3 hours by revenue.

        Steps:
          1. Add HourOfDay derived column
          2. Group by HourOfDay and sum TransactionValue
          3. Sort descending, take top 3
          4. Sum those 3 values

        Same rationale as above — sort + slice cannot be expressed as a
        simple formula, so it is hardcoded.
        """
        enriched = self._add_derived_columns(self.df)
        revenue_by_hour = (
            enriched.groupby('HourOfDay')['TransactionValue']
            .sum()
            .sort_values(ascending=False)
        )
        top_3_revenue = revenue_by_hour.head(3).sum()
        return float(top_3_revenue)

    # =========================================================================
    # CONDITIONAL AGGREGATION
    # =========================================================================

    def _execute_conditional_aggregate(self, func_name: str, args: str) -> float:
        """
        Execute an aggregate with a where/with filter condition.

        Handles:
          sum(revenue where Country != 'United Kingdom')
          sum(revenue where DayOfWeek in ['Saturday', 'Sunday'])
          count(InvoiceNo with Quantity < 0)
        """
        split = re.split(r'\b(where|with)\b', args, maxsplit=1, flags=re.IGNORECASE)
        if len(split) < 3:
            raise ValueError(f"Could not parse conditional args: {args}")

        target = split[0].strip()
        condition = split[2].strip()

        enriched_df = self._add_derived_columns(self.df)
        filtered_df = self._apply_condition(enriched_df, condition)

        # Map 'revenue' alias to the actual computed column
        if target.lower() == 'revenue':
            target = 'TransactionValue'

        if target not in filtered_df.columns:
            raise ValueError(f"Column not found after filtering: {target}")

        if func_name == 'sum':
            return float(filtered_df[target].sum())
        elif func_name in ['count', 'nunique']:
            return float(filtered_df[target].nunique())
        elif func_name in ['avg', 'mean']:
            return float(filtered_df[target].mean())
        else:
            raise ValueError(f"Unsupported function in conditional aggregate: {func_name}")

    def _apply_condition(self, df: pd.DataFrame, condition: str) -> pd.DataFrame:
        """
        Apply a filter condition string to a DataFrame.

        Supported shapes:
          - Column in ['A', 'B']     →  isin membership
          - Column != 'value'        →  string inequality
          - Column < 0               →  numeric comparison (any operator)
        """
        condition = condition.strip()

        # Case 1: in [...] membership
        in_match = re.match(r"(\w+)\s+in\s+\[(.+)\]", condition, re.IGNORECASE)
        if in_match:
            col = in_match.group(1).strip()
            values_raw = in_match.group(2)
            values = [v.strip().strip("'\"") for v in values_raw.split(',')]
            if col not in df.columns:
                raise ValueError(f"Column not found for filter: {col}")
            return df[df[col].isin(values)]

        # Case 2: != inequality
        neq_match = re.match(r"(\w+)\s*!=\s*'?([^']+)'?", condition, re.IGNORECASE)
        if neq_match:
            col = neq_match.group(1).strip()
            val = neq_match.group(2).strip().strip("'\"")
            if col not in df.columns:
                raise ValueError(f"Column not found for filter: {col}")
            return df[df[col] != val]

        # Case 3: numeric comparison
        num_match = re.match(r"(\w+)\s*(<=|>=|<|>)\s*(-?\d+\.?\d*)", condition, re.IGNORECASE)
        if num_match:
            col = num_match.group(1).strip()
            op = num_match.group(2).strip()
            val = float(num_match.group(3))
            if col not in df.columns:
                raise ValueError(f"Column not found for filter: {col}")
            ops = {'<': '__lt__', '>': '__gt__', '<=': '__le__', '>=': '__ge__'}
            return df[getattr(df[col], ops[op])(val)]

        raise ValueError(f"Could not parse condition: {condition}")

    # =========================================================================
    # STANDARD AGGREGATES (no conditions)
    # =========================================================================

    def _execute_sum(self, expression: str) -> float:
        """Execute sum calculation."""
        if '*' in expression:
            parts = [p.strip() for p in expression.split('*')]
            col1, col2 = parts
            if col1 not in self.df.columns or col2 not in self.df.columns:
                raise ValueError(f"Column not found: {col1} or {col2}")
            return float((self.df[col1] * self.df[col2]).sum())
        else:
            col = expression.strip()
            if col not in self.df.columns:
                raise ValueError(f"Column not found: {col}")
            return float(self.df[col].sum())

    def _execute_count(self, expression: str) -> float:
        """Execute count calculation."""
        if 'distinct' in expression.lower():
            return self._execute_distinct_count(expression)
        col = expression.strip()
        if col not in self.df.columns:
            raise ValueError(f"Column not found: {col}")
        return float(self.df[col].count())

    def _execute_distinct_count(self, expression: str) -> float:
        """Execute distinct count calculation."""
        col = re.sub(r'distinct\s+', '', expression, flags=re.IGNORECASE).strip()
        if col not in self.df.columns:
            raise ValueError(f"Column not found: {col}")
        return float(self.df[col].nunique())

    def _execute_avg(self, expression: str) -> float:
        """Execute average calculation."""
        if '*' in expression:
            parts = [p.strip() for p in expression.split('*')]
            col1, col2 = parts
            if col1 not in self.df.columns or col2 not in self.df.columns:
                raise ValueError(f"Column not found: {col1} or {col2}")
            return float((self.df[col1] * self.df[col2]).mean())
        else:
            col = expression.strip()
            if col not in self.df.columns:
                raise ValueError(f"Column not found: {col}")
            return float(self.df[col].mean())

    def _execute_min(self, expression: str) -> float:
        """Execute minimum calculation."""
        col = expression.strip()
        if col not in self.df.columns:
            raise ValueError(f"Column not found: {col}")
        return float(self.df[col].min())

    def _execute_max(self, expression: str) -> float:
        """Execute maximum calculation."""
        col = expression.strip()
        if col not in self.df.columns:
            raise ValueError(f"Column not found: {col}")
        return float(self.df[col].max())

    # =========================================================================
    # RATIO EXECUTION
    # =========================================================================

    def _execute_ratio(self, formula: str, calculated_kpis: dict = None) -> float:
        """
        Execute ratio calculation (metric1 / metric2).

        Splits on '/' and evaluates each side independently.
        Each side can be a previously calculated KPI, a special expression,
        an aggregate function, a column name, or a plain number.
        """
        parts = formula.split('/')
        if len(parts) != 2:
            raise ValueError(f"Invalid ratio formula: {formula}")

        numerator = parts[0].strip()
        denominator = parts[1].strip()

        num_value = self._evaluate_simple_expression(numerator, calculated_kpis)
        den_value = self._evaluate_simple_expression(denominator, calculated_kpis)

        if den_value == 0:
            logger.warning(f"Division by zero in formula: {formula}")
            return 0.0

        return float(num_value / den_value)

    def _evaluate_simple_expression(self, expr: str, calculated_kpis: dict = None) -> float:
        """
        Evaluate one side of a ratio.

        Resolution order:
          1. Previously calculated KPI (e.g. 'total_revenue')
          2. Special hardcoded expression (e.g. 'revenue_top_20_products')
          3. Aggregate function (e.g. 'sum(Quantity)')
          4. Column name (falls back to sum of that column)
          5. Plain number
        """
        expr = expr.strip()

        # 1. Previously calculated KPI
        if calculated_kpis and expr in calculated_kpis:
            return float(calculated_kpis[expr])

        # 2. Special multi-step expressions that can't be expressed as formulas
        if expr == 'revenue_top_20_products':
            return self._compute_revenue_top_20_products()
        if expr == 'revenue_in_top_3_hours':
            return self._compute_revenue_in_top_3_hours()

        # 3. Aggregate function
        if self._is_aggregate_function(expr):
            return self._execute_aggregate(expr)

        # 4. Column name
        if expr in self.df.columns:
            return float(self.df[expr].sum())

        # 5. Plain number
        try:
            return float(expr)
        except ValueError:
            raise ValueError(f"Cannot evaluate expression: {expr}")


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def calculate_kpi_value(df: pd.DataFrame, formula: str) -> float:
    """Convenience function to calculate a single KPI value."""
    parser = FormulaParser(df)
    return parser.parse_and_execute(formula)


# =============================================================================
# TESTS
# =============================================================================

if __name__ == "__main__":
    sample_data = {
        'InvoiceNo': ['001', '001', '002', '003', 'C004', '005'],
        'InvoiceDate': pd.to_datetime([
            '2011-01-01 10:00', '2011-01-01 10:00',
            '2011-01-07 14:00', '2011-01-08 09:00',
            '2011-01-08 11:00', '2011-01-08 12:00'
        ]),
        'Quantity': [2, 3, 1, 5, -1, 2],
        'UnitPrice': [10.0, 15.0, 20.0, 5.0, 10.0, 8.0],
        'CustomerID': ['A', 'A', 'B', 'C', 'A', 'A'],
        'StockCode': ['P1', 'P2', 'P1', 'P3', 'P1', 'P2'],
        'Country': ['United Kingdom', 'United Kingdom', 'Germany',
                    'United Kingdom', 'United Kingdom', 'United Kingdom']
    }
    df = pd.DataFrame(sample_data)

    print("Sample Data:")
    print(df)
    print("\n" + "="*50)

    test_formulas = [
        ("sum(Quantity * UnitPrice)", "Total Revenue"),
        ("count(distinct InvoiceNo)", "Unique Orders"),
        ("sum(Quantity * UnitPrice) / count(distinct InvoiceNo)", "Revenue Per Order"),
        ("count(InvoiceNo with Quantity < 0) / count(distinct InvoiceNo)", "Return Rate"),
        ("sum(revenue where Country != 'United Kingdom') / sum(Quantity * UnitPrice)", "International Share"),
        ("sum(revenue where DayOfWeek in ['Saturday', 'Sunday']) / sum(Quantity * UnitPrice)", "Weekend Share"),
        ("count(distinct CustomerID with orders > 1) / count(distinct CustomerID)", "Repeat Customer Rate"),
        ("count(distinct CustomerID with first_order_date in period)", "New Customers"),
        ("revenue_top_20_products / sum(Quantity * UnitPrice)", "Product Revenue Concentration"),
        ("revenue_in_top_3_hours / sum(Quantity * UnitPrice)", "Peak Hour Concentration"),
    ]

    parser = FormulaParser(df)

    for formula, description in test_formulas:
        try:
            result = parser.parse_and_execute(formula)
            print(f"{description}:")
            print(f"  Formula: {formula}")
            print(f"  Result:  {result}")
            print()
        except Exception as e:
            print(f"{description}: ERROR - {e}\n")