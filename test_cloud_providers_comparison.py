#!/usr/bin/env python3
"""
Cloud Providers Comparison Test для v1.2.0
Сравнивает OpenAI, Anthropic и Gemini по производительности и качеству
"""
import asyncio
import time
import json
from pathlib import Path

from tg_parser.config import settings
from tg_parser.processing import create_processing_pipeline
from tg_parser.storage.sqlalchemy import Database, DatabaseConfig
from tg_parser.storage.sqlalchemy.processed_document_repo import SAProcessedDocumentRepo
from tg_parser.storage.sqlalchemy.processing_failure_repo import SAProcessingFailureRepo
from tg_parser.storage.sqlalchemy.raw_message_repo import SARawMessageRepo


async def test_provider(
    provider: str,
    model: str,
    message_count: int = 10,
    channel_id: str = "labdiagnostica_logical",
    concurrency: int = 1
):
    """Тест одного провайдера"""
    print(f"\n{'='*80}")
    print(f"🧪 Testing {provider.upper()} - {model}")
    print(f"{'='*80}\n")
    
    # Database setup
    config = DatabaseConfig(
        ingestion_state_path=settings.ingestion_state_db_path,
        raw_storage_path=settings.raw_storage_db_path,
        processing_storage_path=settings.processing_storage_db_path,
    )
    db = Database(config)
    await db.init()
    
    try:
        raw_session = db.raw_storage_session()
        processing_session = db.processing_storage_session()
        
        try:
            # Репозитории
            raw_repo = SARawMessageRepo(raw_session)
            processed_repo = SAProcessedDocumentRepo(processing_session)
            failure_repo = SAProcessingFailureRepo(processing_session)
            
            # Pipeline
            print(f"🔧 Creating pipeline for {provider}...")
            pipeline = create_processing_pipeline(
                provider=provider,
                model=model,
                processed_doc_repo=processed_repo,
                failure_repo=failure_repo,
            )
            
            # Загружаем raw сообщения
            all_raw = await raw_repo.list_by_channel(channel_id)
            if not all_raw:
                print(f"❌ No raw messages found for channel {channel_id}")
                return None
            
            # Берём только первые N
            raw_messages = all_raw[:message_count]
            print(f"📦 Processing {len(raw_messages)} messages (concurrency={concurrency})")
            
            # Обработка
            start = time.time()
            processed_docs = await pipeline.process_batch(
                raw_messages,
                force=True,  # Переобработать для чистого теста
                concurrency=concurrency
            )
            elapsed = time.time() - start
            
            # Статистика
            success_count = len(processed_docs)
            failed_count = len(raw_messages) - success_count
            avg_time = elapsed / len(raw_messages) if raw_messages else 0
            throughput = len(raw_messages) / elapsed if elapsed > 0 else 0
            
            print(f"\n📊 Performance Results:")
            print(f"  ✅ Success: {success_count}/{len(raw_messages)} ({success_count/len(raw_messages)*100:.1f}%)")
            print(f"  ❌ Failed: {failed_count}")
            print(f"  ⏱️  Total time: {elapsed:.2f}s")
            print(f"  ⚡ Throughput: {throughput:.3f} msg/sec")
            print(f"  📈 Avg time per message: {avg_time:.2f}s")
            
            # Анализ качества
            if processed_docs:
                print(f"\n🔍 Quality Analysis (sample of 3 docs):")
                
                quality_metrics = {
                    "has_summary": 0,
                    "has_topics": 0,
                    "has_entities": 0,
                    "correct_language": 0,
                    "avg_summary_len": 0,
                    "avg_topics_count": 0,
                    "avg_entities_count": 0,
                }
                
                for doc in processed_docs[:3]:
                    print(f"\n  📄 Doc {doc.id[:20]}...")
                    print(f"    Summary: {doc.summary[:80]}...")
                    print(f"    Topics: {doc.topics[:3]}")
                    print(f"    Entities: {len(doc.entities)} found")
                    print(f"    Language: {doc.language}")
                
                # Метрики по всем документам
                for doc in processed_docs:
                    quality_metrics["has_summary"] += 1 if doc.summary and len(doc.summary) > 10 else 0
                    quality_metrics["has_topics"] += 1 if doc.topics and len(doc.topics) > 0 else 0
                    quality_metrics["has_entities"] += 1 if doc.entities and len(doc.entities) > 0 else 0
                    quality_metrics["correct_language"] += 1 if doc.language == "ru" else 0
                    quality_metrics["avg_summary_len"] += len(doc.summary) if doc.summary else 0
                    quality_metrics["avg_topics_count"] += len(doc.topics) if doc.topics else 0
                    quality_metrics["avg_entities_count"] += len(doc.entities) if doc.entities else 0
                
                total = len(processed_docs)
                quality_metrics["avg_summary_len"] /= total
                quality_metrics["avg_topics_count"] /= total
                quality_metrics["avg_entities_count"] /= total
                
                print(f"\n  📊 Quality Metrics (all {total} docs):")
                print(f"    Has summary: {quality_metrics['has_summary']}/{total} ({quality_metrics['has_summary']/total*100:.1f}%)")
                print(f"    Has topics: {quality_metrics['has_topics']}/{total} ({quality_metrics['has_topics']/total*100:.1f}%)")
                print(f"    Has entities: {quality_metrics['has_entities']}/{total} ({quality_metrics['has_entities']/total*100:.1f}%)")
                print(f"    Correct language (ru): {quality_metrics['correct_language']}/{total} ({quality_metrics['correct_language']/total*100:.1f}%)")
                print(f"    Avg summary length: {quality_metrics['avg_summary_len']:.0f} chars")
                print(f"    Avg topics count: {quality_metrics['avg_topics_count']:.1f}")
                print(f"    Avg entities count: {quality_metrics['avg_entities_count']:.1f}")
                
                return {
                    "provider": provider,
                    "model": model,
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "total_time": elapsed,
                    "avg_time": avg_time,
                    "throughput": throughput,
                    "success_rate": success_count / len(raw_messages) * 100,
                    "quality": quality_metrics,
                }
            else:
                return None
            
        finally:
            await raw_session.close()
            await processing_session.close()
            if hasattr(pipeline, "llm_client") and hasattr(pipeline.llm_client, "close"):
                await pipeline.llm_client.close()
    finally:
        await db.close()


async def main():
    """Запустить сравнительные тесты"""
    print("🚀 TG_parser v1.2.0 — Cloud Providers Comparison")
    print("=" * 80)
    print("\n📋 Test Configuration:")
    print("  • Message count: 10 per provider")
    print("  • Concurrency: 1 (baseline)")
    print("  • Force reprocess: Yes")
    print("  • Channel: labdiagnostica_logical")
    
    # Конфигурация тестов
    tests = [
        ("openai", "gpt-4o-mini"),
        ("anthropic", "claude-3-5-sonnet-20241022"),
        ("gemini", "gemini-2.0-flash-exp"),
    ]
    
    results = []
    
    for provider, model in tests:
        try:
            result = await test_provider(provider, model, message_count=10, concurrency=1)
            if result:
                results.append(result)
        except Exception as e:
            print(f"\n❌ Test failed for {provider}: {e}")
            import traceback
            traceback.print_exc()
        
        # Пауза между провайдерами
        if provider != tests[-1][0]:
            print(f"\n⏸️  Waiting 5 seconds before next provider...")
            await asyncio.sleep(5)
    
    # Сравнительная таблица
    print(f"\n{'='*80}")
    print("📊 COMPARISON TABLE")
    print(f"{'='*80}\n")
    
    if results:
        # Performance сравнение
        print("⚡ Performance:")
        print(f"{'Provider':<15} {'Success Rate':<15} {'Throughput':<15} {'Avg Time':<12}")
        print("-" * 80)
        for r in results:
            print(
                f"{r['provider']:<15} "
                f"{r['success_rate']:.1f}%{' '*10} "
                f"{r['throughput']:.3f} msg/s{' '*3} "
                f"{r['avg_time']:.2f}s"
            )
        
        # Quality сравнение
        print(f"\n📝 Quality:")
        print(f"{'Provider':<15} {'Summary':<10} {'Topics':<10} {'Entities':<10} {'Lang (ru)':<10}")
        print("-" * 80)
        for r in results:
            q = r['quality']
            total = r['success_count']
            print(
                f"{r['provider']:<15} "
                f"{q['has_summary']}/{total}{' '*5} "
                f"{q['has_topics']}/{total}{' '*5} "
                f"{q['has_entities']}/{total}{' '*5} "
                f"{q['correct_language']}/{total}"
            )
        
        # Рекомендация
        print(f"\n💡 Recommendations:")
        best_perf = max(results, key=lambda x: x['throughput'])
        best_quality = max(results, key=lambda x: (
            x['quality']['has_summary'] + 
            x['quality']['has_topics'] + 
            x['quality']['has_entities']
        ))
        
        print(f"  🏆 Best performance: {best_perf['provider']} ({best_perf['throughput']:.3f} msg/s)")
        print(f"  🏆 Best quality: {best_quality['provider']}")
        
        # Сохраняем результаты в JSON
        output_path = Path("test_results_cloud_providers.json")
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\n💾 Results saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())

