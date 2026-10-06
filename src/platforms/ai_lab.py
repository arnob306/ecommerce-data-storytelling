"""
AI Lab page for the Streamlit dashboard.

Shows three panels:
1. Monitoring - live stats from llm_calls.jsonl
2. Narrative comparison - standard vs RAG side by side
3. Prompt version history - all versions with quality metrics

Tenant-aware: reads paths from TenantConfig so it works
identically in single-tenant and multi-tenant modes.
"""

import json
import yaml
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pathlib import Path


def render_ai_lab(config):
    """
    Render the AI Lab page.
    config: TenantConfig instance (single or multi-tenant)
    """
    st.title('AI Lab')
    st.markdown(
        'Observability and evaluation for the LLM narrative pipeline. '
        'Every API call is logged use this page to monitor cost, quality, '
        'and compare prompt versions.'
    )

    tab1, tab2, tab3 = st.tabs([
        '📊 Monitoring',
        '🔬 Narrative Comparison',
        '📝 Prompt Versions'
    ])

    with tab1:
        render_monitoring(config)

    with tab2:
        render_narrative_comparison(config)

    with tab3:
        render_prompt_versions(config)


# ─── MONITORING TAB ───────────────────────────────────────────────────────────

def render_monitoring(config):
    st.subheader('LLM Call Monitoring')

    log_path = config.monitoring_log_path
    if not log_path.exists():
        st.info('No monitoring data yet. Run the narrator to generate narratives.')
        return

    records = load_monitoring_records(log_path)
    if not records:
        st.info('Monitoring log is empty.')
        return

    successful = [r for r in records if r.get('status') == 'success']
    failed = [r for r in records if r.get('status') == 'error']
    total_cost = sum(r.get('estimated_cost_usd', 0) for r in records)
    avg_latency = (
        sum(r.get('latency_ms', 0) for r in successful) / len(successful)
        if successful else 0
    )

    # Top metrics row
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric('Total Calls', len(records))
    col2.metric('Success Rate', f"{len(successful)/len(records)*100:.0f}%")
    col3.metric('Failed', len(failed))
    col4.metric('Total Cost', f'${total_cost:.6f}')
    col5.metric('Avg Latency', f'{avg_latency:.0f}ms')

    st.divider()

    # Per prompt version breakdown
    st.subheader('By Prompt Version')
    versions = {}
    for r in successful:
        v = r.get('prompt_version', 'unknown')
        if v not in versions:
            versions[v] = {
                'calls': 0, 'cost': 0.0, 'latencies': [],
                'flags': [], 'tokens': []
            }
        versions[v]['calls'] += 1
        versions[v]['cost'] += r.get('estimated_cost_usd', 0)
        versions[v]['latencies'].append(r.get('latency_ms', 0))
        versions[v]['flags'].extend(r.get('quality_flags', []))
        versions[v]['tokens'].append(r.get('total_tokens', 0))

    version_rows = []
    for v, stats in versions.items():
        pct_violations = stats['flags'].count('contains_percentages')
        version_rows.append({
            'Version': v,
            'Calls': stats['calls'],
            'Cost (USD)': f"${stats['cost']:.6f}",
            'Avg Latency': f"{sum(stats['latencies'])/len(stats['latencies']):.0f}ms",
            'Avg Tokens': f"{sum(stats['tokens'])/len(stats['tokens']):.0f}",
            '% Violations': f"{pct_violations}/{stats['calls']}",
        })

    if version_rows:
        df = pd.DataFrame(version_rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    # Quality flags breakdown
    all_flags = []
    for r in successful:
        all_flags.extend(r.get('quality_flags', []))

    if all_flags:
        st.subheader('Quality Flags')
        flag_counts = {}
        for flag in all_flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1

        flag_cols = st.columns(len(flag_counts))
        for i, (flag, count) in enumerate(flag_counts.items()):
            flag_cols[i].metric(
                flag.replace('_', ' ').title(),
                count,
                delta=f'{count/len(successful)*100:.0f}% of calls',
                delta_color='inverse'
            )
    else:
        st.success('No quality flags detected across all calls.')

    st.divider()

    # Latency chart over time
    st.subheader('Latency Over Time')
    if successful:
        chart_df = pd.DataFrame([{
            'timestamp': r.get('timestamp', ''),
            'latency_ms': r.get('latency_ms', 0),
            'prompt_version': r.get('prompt_version', 'unknown'),
            'kpi_name': r.get('kpi_name', '')
        } for r in successful])

        chart_df['timestamp'] = pd.to_datetime(
            chart_df['timestamp'], errors='coerce'
        )
        chart_df = chart_df.dropna(subset=['timestamp']).sort_values('timestamp')

        fig = go.Figure()
        for version in chart_df['prompt_version'].unique():
            vdf = chart_df[chart_df['prompt_version'] == version]
            fig.add_trace(go.Scatter(
                x=vdf['timestamp'],
                y=vdf['latency_ms'],
                mode='markers+lines',
                name=version,
                hovertemplate=(
                    '%{x|%Y-%m-%d %H:%M}<br>'
                    'Latency: %{y}ms<br>'
                    '<extra></extra>'
                )
            ))

        fig.update_layout(
            height=300,
            plot_bgcolor='white',
            paper_bgcolor='white',
            xaxis=dict(showgrid=True, gridcolor='#f3f4f6'),
            yaxis=dict(
                showgrid=True, gridcolor='#f3f4f6', title='Latency (ms)'
            ),
            margin=dict(l=0, r=0, t=20, b=0),
            legend=dict(orientation='h', yanchor='bottom', y=1.02)
        )
        st.plotly_chart(fig, use_container_width=True)


# ─── NARRATIVE COMPARISON TAB ─────────────────────────────────────────────────

def render_narrative_comparison(config):
    st.subheader('Standard vs RAG Narrative Comparison')
    st.markdown(
        'Select an anomaly to compare the standard (v2) narrative against '
        'the RAG-enhanced (v2-rag) narrative. The RAG version retrieves '
        'similar historical anomalies before generating, grounding the '
        'output in real patterns rather than speculation.'
    )

    narratives = load_json(config.narratives_path)
    rag_narratives = load_json(config.rag_narratives_path)

    if not narratives:
        st.info('No standard narratives found. Run the narrator first.')
        return
    if not rag_narratives:
        st.info('No RAG narratives found. Run the RAG narrator first.')
        return

    # Build dropdown options from keys present in both
    common_keys = sorted(
        set(narratives.keys()) & set(rag_narratives.keys())
    )
    if not common_keys:
        st.warning('No anomalies found in both narrative files.')
        return

    # Format keys for display
    def format_key(key):
        parts = key.rsplit('_', 1)
        if len(parts) == 2:
            kpi = parts[0].replace('_', ' ').title()
            return f'{kpi} — {parts[1]}'
        return key

    display_options = {format_key(k): k for k in common_keys}
    selected_display = st.selectbox(
        'Select anomaly', list(display_options.keys())
    )
    selected_key = display_options[selected_display]

    std = narratives[selected_key]
    rag = rag_narratives[selected_key]

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.markdown('#### Standard (v2)')
        st.markdown(
            f'*Prompt version: {std.get("prompt_version", "v2")} — '
            f'no historical context*'
        )
        st.info(std.get('narrative', 'No narrative available'))

    with col2:
        st.markdown('#### RAG Enhanced (v2-rag)')
        st.markdown(
            f'*Prompt version: {rag.get("prompt_version", "v2-rag")} — '
            f'retrieves 3 similar past anomalies*'
        )
        st.success(rag.get('narrative', 'No narrative available'))

    # Show retrieved context
    retrieved = rag.get('retrieved_context', [])
    if retrieved:
        st.divider()
        st.markdown('#### Documents Retrieved for Context')
        st.markdown(
            'These are the historical anomalies the RAG system found '
            'most similar to the current one and injected into the prompt:'
        )
        for doc_id in retrieved:
            kpi_part, date_part = doc_id.rsplit('_', 1)
            kpi_display = kpi_part.replace('_', ' ').title()
            st.markdown(f'- **{kpi_display}** — {date_part}')
    else:
        st.caption('No retrieved context recorded for this narrative.')

    st.divider()

    # Metadata comparison
    st.markdown('#### Metadata')
    meta_col1, meta_col2 = st.columns(2)
    with meta_col1:
        st.caption(f"Generated: {std.get('generated_at', 'unknown')[:19]}")
        st.caption(f"Severity: {std.get('severity', 'unknown').upper()}")
    with meta_col2:
        st.caption(f"Generated: {rag.get('generated_at', 'unknown')[:19]}")
        st.caption(f"Retrieved: {len(retrieved)} context documents")


# ─── PROMPT VERSIONS TAB ──────────────────────────────────────────────────────

def render_prompt_versions(config):
    st.subheader('Prompt Version History')
    st.markdown(
        'All prompt versions are tracked in `config/prompts.yaml`. '
        'Each version is a git commit — changes are auditable. '
        'Performance stats come from the monitoring log.'
    )

    # Load prompt config
    prompts_path = config.prompts_config_path
    if not prompts_path.exists():
        st.warning('prompts.yaml not found.')
        return

    with open(prompts_path) as f:
        prompts_config = yaml.safe_load(f)

    versions = prompts_config.get('narrative_prompt', {}).get('versions', [])
    if not versions:
        st.warning('No prompt versions found in prompts.yaml.')
        return

    # Load monitoring records for stats
    log_path = config.monitoring_log_path
    records = load_monitoring_records(log_path) if log_path.exists() else []
    successful = [r for r in records if r.get('status') == 'success']

    # Build stats per version
    version_stats = {}
    for r in successful:
        v = r.get('prompt_version', 'unknown')
        if v not in version_stats:
            version_stats[v] = {'calls': 0, 'flags': [], 'latencies': []}
        version_stats[v]['calls'] += 1
        version_stats[v]['flags'].extend(r.get('quality_flags', []))
        version_stats[v]['latencies'].append(r.get('latency_ms', 0))

    # Display each version
    for version in versions:
        vid = version.get('id', 'unknown')
        desc = version.get('description', '')
        template = version.get('template', '')

        stats = version_stats.get(vid, {})
        calls = stats.get('calls', 0)
        flags = stats.get('flags', [])
        latencies = stats.get('latencies', [])
        pct_violations = flags.count('contains_percentages')
        avg_lat = sum(latencies) / len(latencies) if latencies else 0

        with st.expander(
            f'**{vid}** — {desc}  '
            f'({calls} calls, {pct_violations} violations, {avg_lat:.0f}ms avg)',
            expanded=(vid == versions[-1].get('id'))
        ):
            col1, col2, col3 = st.columns(3)
            col1.metric('Calls', calls)
            col2.metric('% Violations', f'{pct_violations}/{calls}')
            col3.metric('Avg Latency', f'{avg_lat:.0f}ms')

            st.markdown('**Template:**')
            st.code(template.strip(), language='text')


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def load_monitoring_records(log_path: Path) -> list:
    if not log_path.exists():
        return []
    records = []
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)