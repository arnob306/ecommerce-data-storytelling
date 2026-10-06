"""
E-Commerce Analytics Intelligence System - Streamlit Dashboard

Five pages:
  1. Overview      - 16 KPI cards with trend and anomaly status
  2. Time Series   - weekly KPI charts with anomaly markers
  3. Anomalies     - filterable anomaly table with root cause breakdown
  4. Insights      - November 2011 story with LLM narratives
  5. AI Lab        - LLM monitoring, narrative comparison, prompt versions

Run with:
    streamlit run src/platforms/dashboard.py

Requires precompute.py to have been run first:
    python -m src.platforms.precompute
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path
import json
import yaml

import sys
import os
# Ensure project root is on the path regardless of how streamlit is invoked
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.config.tenant_config import TenantConfig
from src.platforms.ai_lab import render_ai_lab

# ============================================================================
# PAGE CONFIG
# ============================================================================

st.set_page_config(
    page_title='E-Commerce Analytics Intelligence',
    page_icon='📊',
    layout='wide',
    initial_sidebar_state='expanded'
)

CACHE_DIR = Path('data/cache')
NARRATIVES_PATH = Path('data/insights/narratives.json')

# ============================================================================
# AUTO-PRECOMPUTE — runs pipeline on first load if cache is missing
# ============================================================================

def cache_is_ready() -> bool:
    """Check all four required cache files exist."""
    required = [
        'kpi_timeseries.parquet',
        'kpi_latest.parquet',
        'anomalies.parquet',
        'root_causes.parquet',
    ]
    return all((CACHE_DIR / f).exists() for f in required)

if not cache_is_ready():
    with st.spinner('First run detected - building data cache (this takes 2-3 minutes)...'):
        try:
            from src.platforms.precompute import precompute_all
            precompute_all()
            st.success('Cache built successfully. Loading dashboard...')
            st.rerun()
        except Exception as e:
            st.error(f'Cache build failed: {e}')
            st.markdown("""
**To fix this, run precompute manually from your project root:**
```bash
python -m src.platforms.precompute
```
Then refresh this page.
""")
            st.stop()

# ============================================================================
# DATA LOADING — cached so it only runs once per session
# ============================================================================

@st.cache_data
def load_kpi_timeseries():
    path = CACHE_DIR / 'kpi_timeseries.parquet'
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df.index = pd.to_datetime(df.index)
    return df

@st.cache_data
def load_kpi_latest():
    path = CACHE_DIR / 'kpi_latest.parquet'
    if not path.exists():
        return None
    return pd.read_parquet(path)

@st.cache_data
def load_anomalies():
    path = CACHE_DIR / 'anomalies.parquet'
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df['date'] = pd.to_datetime(df['date'])
    return df

@st.cache_data
def load_root_causes():
    path = CACHE_DIR / 'root_causes.parquet'
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df['date'] = pd.to_datetime(df['date'])
    return df

@st.cache_data
def load_narratives():
    if not NARRATIVES_PATH.exists():
        return {}
    with open(NARRATIVES_PATH) as f:
        return json.load(f)

# ============================================================================
# CONSTANTS
# ============================================================================

KPI_DISPLAY = {
    'total_revenue': 'Total Revenue',
    'order_count': 'Order Count',
    'units_sold': 'Units Sold',
    'active_customers': 'Active Customers',
    'revenue_per_order': 'Revenue per Order',
    'revenue_per_customer': 'Revenue per Customer',
    'items_per_order': 'Items per Order',
    'avg_unit_price': 'Avg Unit Price',
    'repeat_customer_rate': 'Repeat Customer Rate',
    'product_revenue_concentration': 'Product Revenue Concentration',
    'product_return_rate': 'Product Return Rate',
    'international_revenue_share': 'International Revenue Share',
    'weekend_revenue_share': 'Weekend Revenue Share',
    'peak_hour_concentration': 'Peak Hour Concentration',
    'new_customers': 'New Customers',
    'revenue_by_country': 'Revenue by Country',
}

CURRENCY_KPIS = {
    'total_revenue', 'revenue_per_order', 'revenue_per_customer', 'avg_unit_price'
}

PERCENT_KPIS = {
    'repeat_customer_rate', 'product_revenue_concentration', 'product_return_rate',
    'international_revenue_share', 'weekend_revenue_share', 'peak_hour_concentration'
}

SEVERITY_COLORS = {
    'critical': '#dc2626',
    'high': '#ea580c',
    'medium': '#d97706',
    'low': '#65a30d',
}

# ============================================================================
# FORMATTING HELPERS
# ============================================================================

def format_kpi_value(kpi_name: str, value: float) -> str:
    if kpi_name in CURRENCY_KPIS:
        if value >= 1_000_000:
            return f'£{value/1_000_000:.2f}M'
        elif value >= 1_000:
            return f'£{value:,.0f}'
        else:
            return f'£{value:.2f}'
    elif kpi_name in PERCENT_KPIS:
        return f'{value * 100:.1f}%' if value <= 1 else f'{value:.1f}%'
    else:
        if value >= 1_000_000:
            return f'{value/1_000_000:.1f}M'
        elif value >= 1_000:
            return f'{value:,.0f}'
        else:
            return f'{value:.1f}'

def get_trend(ts_df: pd.DataFrame, kpi: str) -> str:
    if ts_df is None or kpi not in ts_df.columns:
        return ''
    series = ts_df[kpi].dropna()
    if len(series) < 4:
        return ''
    recent = series.iloc[-4:].mean()
    earlier = series.iloc[-8:-4].mean() if len(series) >= 8 else series.iloc[:4].mean()
    if earlier == 0:
        return ''
    change = (recent - earlier) / abs(earlier)
    if change > 0.05:
        return '↑'
    elif change < -0.05:
        return '↓'
    else:
        return '→'

# ============================================================================
# SIDEBAR
# ============================================================================

st.sidebar.title('Analytics Intelligence')
st.sidebar.markdown('UK Retail Dataset  \n541,909 transactions  \nDec 2010 - Dec 2011')
st.sidebar.divider()

page = st.sidebar.radio(
    'Navigate',
    ['Overview', 'Time Series', 'Anomalies', 'Insights', '🧪 AI Lab'],
    label_visibility='collapsed'
)

st.sidebar.divider()
st.sidebar.caption('Run `python -m src.platforms.precompute` to refresh data')
st.sidebar.caption('Run `python -m src.narratives.narrator` for standard narratives')
st.sidebar.caption('Run `python -m src.narratives.rag_narrator` for RAG narratives')

# Tenant config - single-tenant by default, multi-tenant ready
tenant_config = TenantConfig()

# ============================================================================
# CHECK CACHE
# ============================================================================

ts_df = load_kpi_timeseries()
latest_df = load_kpi_latest()
anomalies_df = load_anomalies()
rc_df = load_root_causes()
narratives = load_narratives()

if ts_df is None:
    st.error('Cache not found. Run `python -m src.platform.precompute` first.')
    st.stop()

# ============================================================================
# PAGE 1: OVERVIEW
# ============================================================================

if page == 'Overview':
    st.title('E-Commerce Analytics Intelligence')
    st.caption('Automated KPI monitoring, anomaly detection, and root cause analysis')
    st.divider()

    if latest_df is None:
        st.warning('Latest KPI data not found.')
        st.stop()

    latest = latest_df.iloc[0]

    # Count anomalies per KPI for status indicators
    anomaly_kpis = set()
    if anomalies_df is not None:
        anomaly_kpis = set(anomalies_df['kpi_name'].unique())

    # KPI categories
    categories = {
        'Finance': ['total_revenue', 'revenue_per_order', 'revenue_per_customer'],
        'Operations': ['order_count', 'items_per_order', 'units_sold', 'product_return_rate', 'weekend_revenue_share', 'peak_hour_concentration'],
        'Growth': ['active_customers', 'repeat_customer_rate', 'new_customers'],
        'Product': ['product_revenue_concentration', 'avg_unit_price'],
        'International': ['international_revenue_share'],
    }

    for category, kpis in categories.items():
        st.subheader(category)
        cols = st.columns(len(kpis))

        for col, kpi in zip(cols, kpis):
            if kpi not in latest:
                continue

            value = latest[kpi]
            display_name = KPI_DISPLAY.get(kpi, kpi)
            formatted = format_kpi_value(kpi, value)
            trend = get_trend(ts_df, kpi)
            has_anomaly = kpi in anomaly_kpis

            with col:
                if has_anomaly:
                    st.metric(
                        label=f'{display_name} 🔴',
                        value=formatted,
                        delta=trend if trend else None,
                        delta_color='normal'
                    )
                else:
                    st.metric(
                        label=display_name,
                        value=formatted,
                        delta=trend if trend else None,
                        delta_color='normal'
                    )

        st.divider()

    # Summary stats
    if anomalies_df is not None:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric('Total Anomalies', len(anomalies_df))
        col2.metric('Critical', len(anomalies_df[anomalies_df['severity'] == 'critical']))
        col3.metric('High', len(anomalies_df[anomalies_df['severity'] == 'high']))
        col4.metric('KPIs Affected', anomalies_df['kpi_name'].nunique())

# ============================================================================
# PAGE 2: TIME SERIES
# ============================================================================

elif page == 'Time Series':
    st.title('KPI Time Series')
    st.caption('Weekly KPI values with anomaly dates flagged')
    st.divider()

    available_kpis = [k for k in KPI_DISPLAY.keys() if k in ts_df.columns]
    display_options = [KPI_DISPLAY.get(k, k) for k in available_kpis]

    selected_display = st.selectbox('Select KPI', display_options)
    selected_kpi = available_kpis[display_options.index(selected_display)]

    series = ts_df[selected_kpi].dropna()

    if len(series) == 0:
        st.warning('No data available for this KPI.')
        st.stop()

    # Get anomaly dates for this KPI
    kpi_anomalies = pd.DataFrame()
    if anomalies_df is not None:
        kpi_anomalies = anomalies_df[
            (anomalies_df['kpi_name'] == selected_kpi) &
            (anomalies_df['method'] != 'mann_kendall')
        ]

    # Build chart
    fig = go.Figure()

    # Main line
    fig.add_trace(go.Scatter(
        x=series.index,
        y=series.values,
        mode='lines',
        name=selected_display,
        line=dict(color='#3b82f6', width=2),
        hovertemplate='%{x|%Y-%m-%d}<br>' + selected_display + ': %{y:,.2f}<extra></extra>'
    ))

    # Anomaly markers
    if len(kpi_anomalies) > 0:
        for _, anomaly in kpi_anomalies.iterrows():
            anomaly_date = pd.Timestamp(anomaly['date'])
            if anomaly_date in series.index:
                color = SEVERITY_COLORS.get(anomaly['severity'], '#6b7280')
                fig.add_vline(
                    x=anomaly_date,
                    line_dash='dash',
                    line_color=color,
                    opacity=0.6
                )
                fig.add_annotation(
                    x=anomaly_date,
                    y=series.max(),
                    text=anomaly['severity'].upper()[0],
                    showarrow=False,
                    font=dict(color=color, size=10),
                    yshift=10
                )

    fig.update_layout(
        height=450,
        showlegend=False,
        plot_bgcolor='white',
        paper_bgcolor='white',
        xaxis=dict(showgrid=True, gridcolor='#f3f4f6'),
        yaxis=dict(showgrid=True, gridcolor='#f3f4f6'),
        margin=dict(l=0, r=0, t=20, b=0),
        hovermode='x unified'
    )

    st.plotly_chart(fig, use_container_width=True)

    # Stats below chart
    col1, col2, col3, col4 = st.columns(4)
    col1.metric('Mean', format_kpi_value(selected_kpi, series.mean()))
    col2.metric('Min', format_kpi_value(selected_kpi, series.min()))
    col3.metric('Max', format_kpi_value(selected_kpi, series.max()))
    col4.metric('Anomalies Detected', len(kpi_anomalies))

    if len(kpi_anomalies) > 0:
        st.subheader('Detected Anomalies')
        display_cols = ['date', 'severity', 'confidence', 'deviation_pct', 'method', 'description']
        display_cols = [c for c in display_cols if c in kpi_anomalies.columns]
        st.dataframe(
            kpi_anomalies[display_cols].sort_values('date'),
            use_container_width=True,
            hide_index=True
        )

# ============================================================================
# PAGE 3: ANOMALIES
# ============================================================================

elif page == 'Anomalies':
    st.title('Anomaly Explorer')
    st.caption('47 anomalies detected across 13 KPIs. Click a row to see root cause breakdown.')
    st.divider()

    if anomalies_df is None:
        st.warning('Anomaly data not found.')
        st.stop()

    # Filters
    col1, col2 = st.columns(2)
    with col1:
        severity_filter = st.multiselect(
            'Filter by severity',
            ['critical', 'high', 'medium', 'low'],
            default=['critical', 'high', 'medium', 'low']
        )
    with col2:
        kpi_options = sorted(anomalies_df['kpi_name'].unique())
        kpi_filter = st.multiselect(
            'Filter by KPI',
            kpi_options,
            default=kpi_options
        )

    filtered = anomalies_df[
        (anomalies_df['severity'].isin(severity_filter)) &
        (anomalies_df['kpi_name'].isin(kpi_filter))
    ].copy()

    filtered['date_fmt'] = filtered['date'].dt.strftime('%Y-%m-%d')
    filtered['confidence_pct'] = (filtered['confidence'] * 100).round(0).astype(int).astype(str) + '%'
    filtered['deviation_fmt'] = filtered['deviation_pct'].round(1).astype(str) + '%'

    st.caption(f'Showing {len(filtered)} anomalies')

    # Severity colour pills
    def severity_badge(s):
        colors = {'critical': '🔴', 'high': '🟠', 'medium': '🟡', 'low': '🟢'}
        return colors.get(s, '') + ' ' + s.upper()

    filtered['severity_display'] = filtered['severity'].apply(severity_badge)

    display_df = filtered[['date_fmt', 'kpi_name', 'severity_display', 'confidence_pct', 'deviation_fmt', 'method']].copy()
    display_df.columns = ['Date', 'KPI', 'Severity', 'Confidence', 'Deviation', 'Method']

    selected_rows = st.dataframe(
        display_df.sort_values('Date'),
        use_container_width=True,
        hide_index=True,
        on_select='rerun',
        selection_mode='single-row'
    )

    # Root cause breakdown for selected anomaly
    if selected_rows and selected_rows.selection.rows:
        idx = selected_rows.selection.rows[0]
        selected_anomaly = filtered.iloc[idx]

        st.divider()
        kpi_name = selected_anomaly['kpi_name']
        date_str = selected_anomaly['date_fmt']
        st.subheader(f'Root Cause: {KPI_DISPLAY.get(kpi_name, kpi_name)} on {date_str}')

        if rc_df is not None:
            rc_match = rc_df[
                (rc_df['kpi_name'] == kpi_name) &
                (rc_df['date'].dt.strftime('%Y-%m-%d') == date_str)
            ]

            if len(rc_match) > 0:
                rc_row = rc_match.iloc[0]

                if rc_row['status'] == 'analysed':
                    # Build segment contribution chart
                    segments = []
                    for i in range(1, 4):
                        dim = rc_row.get(f'driver_{i}_dimension')
                        seg = rc_row.get(f'driver_{i}_segment')
                        pct = rc_row.get(f'driver_{i}_contribution_pct')
                        if pd.notna(dim) and pd.notna(pct):
                            segments.append({
                                'Driver': f'{dim}={seg}',
                                'Contribution (%)': float(pct)
                            })

                    if segments:
                        seg_df = pd.DataFrame(segments)
                        fig = px.bar(
                            seg_df,
                            x='Contribution (%)',
                            y='Driver',
                            orientation='h',
                            color='Contribution (%)',
                            color_continuous_scale=['#dc2626', '#f3f4f6', '#3b82f6'],
                            color_continuous_midpoint=0
                        )
                        fig.update_layout(
                            height=250,
                            showlegend=False,
                            plot_bgcolor='white',
                            paper_bgcolor='white',
                            margin=dict(l=0, r=0, t=20, b=0),
                            coloraxis_showscale=False
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    # LLM narrative
                    narrative_key = f"{kpi_name}_{date_str}"
                    if narrative_key in narratives:
                        st.info(narratives[narrative_key]['narrative'])
                    else:
                        st.caption('No AI narrative yet. Run `python -m src.narratives.narrator` to generate.')

                    st.caption(f"Summary: {rc_row.get('summary', '')}")

                else:
                    st.caption(f"Status: {rc_row['status'].replace('_', ' ').title()}")
                    st.caption('This metric requires manual investigation - it is a ratio KPI that cannot be directly segmented by dimension.')
            else:
                st.caption('No root cause data found for this anomaly.')

# ============================================================================
# PAGE 4: INSIGHTS
# ============================================================================

elif page == 'Insights':
    st.title('Key Insights')
    st.caption('What the data actually found')
    st.divider()

    st.subheader('The November 2011 Event')
    st.markdown("""
Four separate anomalies were detected in late November 2011 across active_customers, order_count, 
total_revenue, and units_sold. Root cause analysis revealed they all trace back to the same cause.
""")

    if rc_df is not None and ts_df is not None:
        nov_kpis = ['active_customers', 'order_count', 'total_revenue', 'units_sold']
        nov_dates = ['2011-11-13', '2011-11-20']

        # Plot the four KPIs together around the spike period
        fig = go.Figure()
        colors = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6']

        for kpi, color in zip(nov_kpis, colors):
            if kpi not in ts_df.columns:
                continue
            series = ts_df[kpi].dropna()
            # Normalise to % of mean for comparison on same axis
            mean = series.mean()
            normalised = (series / mean) * 100

            fig.add_trace(go.Scatter(
                x=series.index,
                y=normalised.values,
                mode='lines',
                name=KPI_DISPLAY.get(kpi, kpi),
                line=dict(color=color, width=2),
                hovertemplate='%{x|%Y-%m-%d}<br>%{y:.1f}% of mean<extra>' + KPI_DISPLAY.get(kpi, kpi) + '</extra>'
            ))

        # Mark the November spike window
        fig.add_vrect(
            x0='2011-11-06', x1='2011-11-27',
            fillcolor='#fef3c7', opacity=0.4,
            layer='below', line_width=0,
            annotation_text='November spike',
            annotation_position='top left'
        )

        fig.update_layout(
            height=400,
            plot_bgcolor='white',
            paper_bgcolor='white',
            xaxis=dict(showgrid=True, gridcolor='#f3f4f6'),
            yaxis=dict(showgrid=True, gridcolor='#f3f4f6', title='% of weekly mean'),
            margin=dict(l=0, r=0, t=20, b=0),
            legend=dict(orientation='h', yanchor='bottom', y=1.02)
        )

        st.plotly_chart(fig, use_container_width=True)

    st.markdown("""
**What root cause analysis found:**

All four metrics trace to the same dimensional drivers - UK customers purchasing 
two specific products (StockCode 23084 and 22086) at unusually high volumes 
during afternoon hours (12:00-17:00) across three consecutive weeks.

This is consistent with pre-Christmas wholesale buying behaviour. The pattern 
showing up across four KPIs simultaneously is not four separate anomalies - 
it is one event.
""")

    st.divider()

    # Show narratives for the November anomalies
    if narratives:
        st.subheader('AI-Generated Summaries')
        nov_narratives = {
            k: v for k, v in narratives.items()
            if '2011-11' in k
        }
        if nov_narratives:
            for key, nav in nov_narratives.items():
                with st.expander(f"{KPI_DISPLAY.get(nav['kpi_name'], nav['kpi_name'])} - {nav['date'][:10]}"):
                    st.write(nav['narrative'])
        else:
            st.caption('Run `python -m src.narratives.narrator` to generate AI summaries.')
    else:
        st.caption('Run `python -m src.narratives.narrator` to generate AI summaries for these anomalies.')

    st.divider()
    st.subheader('Other Notable Findings')

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
**Upward growth trends throughout 2011**

Mann-Kendall trend detection flagged statistically significant upward trends 
in revenue, order count, active customers, and units sold across the full year. 
The business was growing consistently, not just spiking at Christmas.
""")
    with col2:
        st.markdown("""
**Return rate declining (positive signal)**

Product return rate showed a statistically significant downward trend 
(p=0.007). Fewer returns over time suggests improving product-market fit 
or better product descriptions reducing buyer mismatch.
""")

elif page == '🧪 AI Lab':
    render_ai_lab(tenant_config)