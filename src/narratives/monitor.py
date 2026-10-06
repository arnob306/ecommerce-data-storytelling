"""
LLM Monitoring Layer - observability for every AI call in the system.

Logs every LLM call to data/monitoring/llm_calls.jsonl with:
  - Timestamp and model
  - Prompt version ID
  - Token usage (input and output separately)
  - Estimated cost in USD
  - Latency in milliseconds
  - Basic output quality flags

Design decisions:
  - JSONL format (one JSON object per line) rather than a database.
    Reason: no database exists yet, JSONL is human-readable, appendable
    without locking, and directly ingestible into PostgreSQL in Phase 7
    with a single COPY command.

  - Input and output tokens tracked separately.
    Reason: they have different costs. Knowing you spend 80% of cost on
    input tokens tells you to shorten prompts. Aggregating them loses
    that signal.

  - Quality flags are heuristic, not ML-based.
    Reason: no ground truth labels exist to train a real evaluator.
    Heuristics catch obvious failures (empty output, runaway length)
    without pretending to measure quality they cannot measure.

  - Cost estimates use Groq's public pricing for llama-3.1-8b-instant.
    Reason: even rough cost tracking surfaces surprises. If narratives
    start costing 10x more than expected, something changed in the prompt
    or the model behaviour.

Usage:
    from src.narratives.monitor import LLMMonitor
    monitor = LLMMonitor()
    with monitor.track(prompt_version='v1', model='llama-3.1-8b-instant') as call:
        response = client.chat.completions.create(...)
        call.record(response)
"""

import json
import time
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Generator

logger = logging.getLogger(__name__)

MONITORING_DIR = Path('data/monitoring')
LOG_FILE = MONITORING_DIR / 'llm_calls.jsonl'

# Groq pricing for llama-3.1-8b-instant (USD per million tokens)
# Source: console.groq.com/docs/openai (update if pricing changes)
COST_PER_M_INPUT_TOKENS = 0.05
COST_PER_M_OUTPUT_TOKENS = 0.08

# Quality thresholds
MIN_OUTPUT_CHARS = 50      # below this = likely failed generation
MAX_OUTPUT_CHARS = 600     # above this = likely ignored length instruction
MIN_OUTPUT_SENTENCES = 1
MAX_OUTPUT_SENTENCES = 6


@dataclass
class LLMCallRecord:
    """
    Represents a single LLM call with all observable attributes.
    Written as one line to llm_calls.jsonl on completion.
    """
    timestamp: str = ''
    model: str = ''
    prompt_version: str = ''
    kpi_name: str = ''
    anomaly_date: str = ''
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    output_length_chars: int = 0
    output_sentence_count: int = 0
    quality_flags: list = field(default_factory=list)
    status: str = 'pending'  # pending, success, error
    error_message: str = ''

    def compute_cost(self):
        """Estimate cost from token counts using Groq pricing."""
        input_cost = (self.input_tokens / 1_000_000) * COST_PER_M_INPUT_TOKENS
        output_cost = (self.output_tokens / 1_000_000) * COST_PER_M_OUTPUT_TOKENS
        self.estimated_cost_usd = round(input_cost + output_cost, 8)

    def evaluate_quality(self, output_text: str):
        """
        Apply heuristic quality checks to the output.

        Not ML-based — catches obvious failures without pretending
        to measure semantic quality it cannot measure.
        """
        flags = []
        self.output_length_chars = len(output_text)
        self.output_sentence_count = output_text.count('.') + output_text.count('!')

        if self.output_length_chars < MIN_OUTPUT_CHARS:
            flags.append('output_too_short')
        if self.output_length_chars > MAX_OUTPUT_CHARS:
            flags.append('output_too_long')
        if self.output_sentence_count > MAX_OUTPUT_SENTENCES:
            flags.append('too_many_sentences')
        if output_text.strip() == '':
            flags.append('empty_output')
        if output_text.lower().startswith('i '):
            flags.append('starts_with_i')  # prompt violation
        if 'percent' in output_text.lower() or '%' in output_text:
            flags.append('contains_percentages')  # prompt violation

        self.quality_flags = flags

    def to_dict(self) -> dict:
        d = asdict(self)
        d['quality_flags'] = self.quality_flags
        return d


class LLMMonitor:
    """
    Monitors and logs all LLM calls in the system.

    Usage:
        monitor = LLMMonitor()

        # Context manager approach - tracks latency automatically
        with monitor.track('v1', 'llama-3.1-8b-instant', 'total_revenue', '2011-11-20') as call:
            response = groq_client.chat.completions.create(...)
            call.record_response(response)

        # Or record manually
        monitor.log_call(record)
    """

    def __init__(self):
        MONITORING_DIR.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def track(
        self,
        prompt_version: str,
        model: str,
        kpi_name: str = '',
        anomaly_date: str = ''
    ) -> Generator[LLMCallRecord, None, None]:
        """
        Context manager that times the LLM call and logs the result.

        Usage:
            with monitor.track('v1', 'llama-3.1-8b-instant') as call:
                response = client.chat.completions.create(...)
                call.record_response(response)
        """
        record = LLMCallRecord(
            timestamp=datetime.now().isoformat(),
            model=model,
            prompt_version=prompt_version,
            kpi_name=kpi_name,
            anomaly_date=anomaly_date
        )

        start_time = time.time()

        try:
            yield record
            record.latency_ms = int((time.time() - start_time) * 1000)
            record.status = 'success'
        except Exception as e:
            record.latency_ms = int((time.time() - start_time) * 1000)
            record.status = 'error'
            record.error_message = str(e)
            logger.error(f'LLM call failed: {e}')
            raise
        finally:
            self._write_record(record)

    def record_response(self, record: LLMCallRecord, response, output_text: str):
        """
        Extract token usage and quality metrics from a Groq response object.

        Call this inside the track() context manager after receiving response.
        """
        if hasattr(response, 'usage') and response.usage:
            record.input_tokens = response.usage.prompt_tokens or 0
            record.output_tokens = response.usage.completion_tokens or 0
            record.total_tokens = response.usage.total_tokens or 0
            record.compute_cost()

        record.evaluate_quality(output_text)

    def _write_record(self, record: LLMCallRecord):
        """Append one record as a JSON line to the log file."""
        try:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record.to_dict()) + '\n')
        except Exception as e:
            logger.error(f'Failed to write monitoring record: {e}')

    def load_logs(self) -> list[dict]:
        """Load all log records as a list of dicts."""
        if not LOG_FILE.exists():
            return []
        records = []
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records

    def summary(self) -> dict:
        """
        Produce a summary of all logged calls.

        Returns aggregated stats useful for the dashboard monitoring view:
        total calls, success rate, total cost, average latency,
        quality flag breakdown, and per-prompt-version comparison.
        """
        records = self.load_logs()
        if not records:
            return {'total_calls': 0, 'message': 'No calls logged yet'}

        total = len(records)
        successful = [r for r in records if r.get('status') == 'success']
        failed = [r for r in records if r.get('status') == 'error']

        total_cost = sum(r.get('estimated_cost_usd', 0) for r in records)
        avg_latency = (
            sum(r.get('latency_ms', 0) for r in successful) / len(successful)
            if successful else 0
        )
        avg_tokens = (
            sum(r.get('total_tokens', 0) for r in successful) / len(successful)
            if successful else 0
        )

        # Quality flag counts
        all_flags = []
        for r in successful:
            all_flags.extend(r.get('quality_flags', []))
        flag_counts = {}
        for flag in all_flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1

        # Per prompt version breakdown
        versions = {}
        for r in successful:
            v = r.get('prompt_version', 'unknown')
            if v not in versions:
                versions[v] = {'calls': 0, 'total_cost': 0, 'avg_latency_ms': 0, 'latencies': []}
            versions[v]['calls'] += 1
            versions[v]['total_cost'] += r.get('estimated_cost_usd', 0)
            versions[v]['latencies'].append(r.get('latency_ms', 0))

        for v in versions:
            lats = versions[v].pop('latencies')
            versions[v]['avg_latency_ms'] = round(sum(lats) / len(lats)) if lats else 0
            versions[v]['total_cost'] = round(versions[v]['total_cost'], 6)

        return {
            'total_calls': total,
            'successful': len(successful),
            'failed': len(failed),
            'success_rate_pct': round(len(successful) / total * 100, 1),
            'total_cost_usd': round(total_cost, 6),
            'avg_latency_ms': round(avg_latency),
            'avg_tokens_per_call': round(avg_tokens),
            'quality_flags': flag_counts,
            'by_prompt_version': versions,
        }

    def print_summary(self):
        """Print a readable monitoring summary to stdout."""
        s = self.summary()
        if s.get('total_calls', 0) == 0:
            print('No LLM calls logged yet.')
            return

        print('\n' + '='*60)
        print('LLM MONITORING SUMMARY')
        print('='*60)
        print(f'Total calls:      {s["total_calls"]}')
        print(f'Success rate:     {s["success_rate_pct"]}%')
        print(f'Total cost:       ${s["total_cost_usd"]:.6f} USD')
        print(f'Avg latency:      {s["avg_latency_ms"]}ms')
        print(f'Avg tokens/call:  {s["avg_tokens_per_call"]}')

        if s.get('quality_flags'):
            print('\nQuality flags:')
            for flag, count in s['quality_flags'].items():
                print(f'  {flag}: {count}')

        if s.get('by_prompt_version'):
            print('\nBy prompt version:')
            for version, stats in s['by_prompt_version'].items():
                print(f'  {version}: {stats["calls"]} calls, '
                      f'${stats["total_cost"]:.6f}, '
                      f'{stats["avg_latency_ms"]}ms avg')
        print('='*60)


if __name__ == '__main__':
    monitor = LLMMonitor()
    monitor.print_summary()