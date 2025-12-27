#!/usr/bin/env python
"""
Compare Agent-based processing vs v1.2 Pipeline.

Phase 2D: Quality comparison script.
Reads sample messages and compares results from both approaches.
"""

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tg_parser.agents import TGProcessingAgent
from tg_parser.agents.tools.text_tools import (
    _basic_clean_text,
    _basic_extract_entities,
    _basic_extract_topics,
)
from tg_parser.domain.models import MessageType, RawTelegramMessage


@dataclass
class ComparisonResult:
    """Result of comparing two processing approaches."""
    message_id: str
    text_preview: str
    
    # Pipeline v1.2 results (from kb_entries.ndjson)
    pipeline_topics: list[str]
    pipeline_summary: str | None
    pipeline_entities_count: int
    
    # Agent basic results
    agent_basic_topics: list[str]
    agent_basic_summary: str | None
    agent_basic_entities_count: int
    agent_basic_time_ms: float
    
    # Agent LLM results (if available)
    agent_llm_topics: list[str] | None = None
    agent_llm_summary: str | None = None
    agent_llm_entities_count: int | None = None
    agent_llm_key_points: list[str] | None = None
    agent_llm_sentiment: str | None = None
    agent_llm_time_ms: float | None = None


def load_kb_entries(path: str, limit: int = 20) -> list[dict]:
    """Load KB entries from NDJSON file."""
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= limit:
                break
            if line.strip():
                entries.append(json.loads(line))
    return entries


def kb_entry_to_raw_message(entry: dict) -> RawTelegramMessage:
    """Convert KB entry back to RawTelegramMessage for reprocessing."""
    source = entry.get("source", {})
    
    # Extract original text from content (contains summary + original)
    # For this comparison, we'll use the content field
    text = entry.get("content", "")
    
    return RawTelegramMessage(
        id=source.get("message_id", "0"),
        channel_id=source.get("channel_id", "unknown"),
        message_type=MessageType.POST,
        date=datetime.now(UTC),
        text=text,
        source_ref=source.get("source_ref", f"test:{source.get('message_id', '0')}"),
        raw_payload={},
    )


async def process_with_basic_agent(message: RawTelegramMessage) -> tuple[dict, float]:
    """Process message with basic agent tools (no LLM calls)."""
    start = time.perf_counter()
    
    # Use basic tools directly (faster, no API calls)
    clean_result = _basic_clean_text(message.text)
    topics_result = _basic_extract_topics(message.text)
    entities_result = _basic_extract_entities(message.text)
    
    elapsed_ms = (time.perf_counter() - start) * 1000
    
    return {
        "text_clean": clean_result.text_clean,
        "language": clean_result.language,
        "topics": topics_result.topics,
        "summary": topics_result.summary,
        "entities": [{"type": e.type, "value": e.value} for e in entities_result.entities],
    }, elapsed_ms


async def process_with_llm_agent(
    message: RawTelegramMessage, 
    agent: TGProcessingAgent
) -> tuple[dict, float]:
    """Process message with LLM-enhanced agent."""
    start = time.perf_counter()
    
    try:
        doc = await agent.process(message)
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        return {
            "text_clean": doc.text_clean,
            "language": doc.language,
            "topics": doc.topics,
            "summary": doc.summary,
            "entities": [{"type": e.type, "value": e.value} for e in doc.entities],
            "key_points": doc.metadata.get("key_points", []),
            "sentiment": doc.metadata.get("sentiment"),
        }, elapsed_ms
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        print(f"  ⚠️  LLM agent error: {e}")
        return None, elapsed_ms


def compare_topics(topics1: list[str], topics2: list[str]) -> dict:
    """Compare two topic lists."""
    set1 = set(t.lower() for t in topics1)
    set2 = set(t.lower() for t in topics2)
    
    common = set1 & set2
    only_1 = set1 - set2
    only_2 = set2 - set1
    
    # Jaccard similarity
    if set1 or set2:
        similarity = len(common) / len(set1 | set2)
    else:
        similarity = 1.0
    
    return {
        "common": list(common),
        "only_pipeline": list(only_1),
        "only_agent": list(only_2),
        "similarity": similarity,
    }


async def run_comparison(
    kb_path: str = "output/kb_entries.ndjson",
    limit: int = 10,
    include_llm: bool = False,
):
    """Run comparison between pipeline and agent processing."""
    print("=" * 70)
    print("🔬 Agent vs Pipeline Comparison")
    print("=" * 70)
    print()
    
    # Load KB entries
    print(f"📂 Loading entries from {kb_path}...")
    entries = load_kb_entries(kb_path, limit)
    print(f"   Loaded {len(entries)} entries")
    print()
    
    # Prepare LLM agent if needed
    llm_agent = None
    if include_llm:
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            from tg_parser.processing.llm.factory import create_llm_client
            llm_client = create_llm_client(
                provider="openai",
                api_key=api_key,
                model="gpt-4o-mini",
            )
            llm_agent = TGProcessingAgent(
                model="gpt-4o-mini",
                provider="openai",
                use_llm_tools=True,
                llm_client=llm_client,
            )
            print("🤖 LLM Agent initialized")
        else:
            print("⚠️  No OPENAI_API_KEY, skipping LLM comparison")
            include_llm = False
    
    # Process and compare
    results = []
    total_basic_time = 0.0
    total_llm_time = 0.0
    topic_similarities = []
    
    print()
    print("Processing messages...")
    print("-" * 70)
    
    for i, entry in enumerate(entries, 1):
        msg_id = entry.get("source", {}).get("message_id", str(i))
        text_preview = entry.get("content", "")[:60] + "..."
        
        print(f"\n[{i}/{len(entries)}] Message {msg_id}")
        print(f"   Text: {text_preview}")
        
        # Get pipeline results from KB entry
        pipeline_topics = entry.get("topics", [])
        pipeline_summary = entry.get("content", "").split("\n")[0] if entry.get("content") else None
        
        # Convert to RawTelegramMessage
        raw_msg = kb_entry_to_raw_message(entry)
        
        # Process with basic agent
        basic_result, basic_time = await process_with_basic_agent(raw_msg)
        total_basic_time += basic_time
        
        print(f"   ✅ Basic agent: {basic_time:.1f}ms, {len(basic_result['topics'])} topics")
        
        # Process with LLM agent if available
        llm_result = None
        llm_time = 0.0
        if include_llm and llm_agent:
            llm_result, llm_time = await process_with_llm_agent(raw_msg, llm_agent)
            total_llm_time += llm_time
            if llm_result:
                print(f"   ✅ LLM agent: {llm_time:.1f}ms, {len(llm_result['topics'])} topics")
        
        # Compare topics
        topic_comp = compare_topics(pipeline_topics, basic_result["topics"])
        topic_similarities.append(topic_comp["similarity"])
        
        print(f"   📊 Topic similarity: {topic_comp['similarity']:.1%}")
        if topic_comp["common"]:
            print(f"      Common: {', '.join(topic_comp['common'][:3])}")
        if topic_comp["only_pipeline"]:
            print(f"      Only pipeline: {', '.join(topic_comp['only_pipeline'][:3])}")
        if topic_comp["only_agent"]:
            print(f"      Only agent: {', '.join(topic_comp['only_agent'][:3])}")
        
        # Store result
        result = ComparisonResult(
            message_id=msg_id,
            text_preview=text_preview,
            pipeline_topics=pipeline_topics,
            pipeline_summary=pipeline_summary,
            pipeline_entities_count=0,  # Not available in KB entry
            agent_basic_topics=basic_result["topics"],
            agent_basic_summary=basic_result["summary"],
            agent_basic_entities_count=len(basic_result["entities"]),
            agent_basic_time_ms=basic_time,
        )
        
        if llm_result:
            result.agent_llm_topics = llm_result["topics"]
            result.agent_llm_summary = llm_result["summary"]
            result.agent_llm_entities_count = len(llm_result["entities"])
            result.agent_llm_key_points = llm_result.get("key_points")
            result.agent_llm_sentiment = llm_result.get("sentiment")
            result.agent_llm_time_ms = llm_time
        
        results.append(result)
    
    # Summary
    print()
    print("=" * 70)
    print("📊 SUMMARY")
    print("=" * 70)
    
    avg_similarity = sum(topic_similarities) / len(topic_similarities) if topic_similarities else 0
    avg_basic_time = total_basic_time / len(entries) if entries else 0
    
    print(f"""
Messages processed:     {len(entries)}
Average topic similarity: {avg_similarity:.1%}

Basic Agent:
  - Average time:       {avg_basic_time:.1f}ms
  - Total time:         {total_basic_time:.0f}ms
""")
    
    if include_llm and total_llm_time > 0:
        avg_llm_time = total_llm_time / len(entries)
        print(f"""LLM Agent:
  - Average time:       {avg_llm_time:.1f}ms
  - Total time:         {total_llm_time:.0f}ms
  - Speedup vs LLM:     {avg_llm_time / avg_basic_time:.1f}x slower
""")
    
    print("=" * 70)
    print("✅ Comparison complete!")
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Compare Agent vs Pipeline processing")
    parser.add_argument("--limit", type=int, default=10, help="Number of messages to compare")
    parser.add_argument("--llm", action="store_true", help="Include LLM agent comparison")
    parser.add_argument("--kb-path", type=str, default="output/kb_entries.ndjson", help="Path to KB entries")
    args = parser.parse_args()
    
    asyncio.run(run_comparison(
        kb_path=args.kb_path,
        limit=args.limit,
        include_llm=args.llm,
    ))

