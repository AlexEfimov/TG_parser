#!/usr/bin/env python3
"""
Anthropic & Gemini Testing для v1.2.0
Тестирует только Anthropic и Gemini (OpenAI уже протестирован)
"""

import asyncio
import json
import time
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
    concurrency: int = 1,
):
    """Тест одного провайдера"""
    print(f"\n{'=' * 80}")
    print(f"🧪 Testing {provider.upper()} - {model}")
    print(f"{'=' * 80}\n")

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
                concurrency=concurrency,
            )
            elapsed = time.time() - start

            # Статистика
            success_count = len(processed_docs)
            failed_count = len(raw_messages) - success_count
            avg_time = elapsed / len(raw_messages) if raw_messages else 0
            throughput = len(raw_messages) / elapsed if elapsed > 0 else 0

            print("\n📊 Performance Results:")
            print(
                f"  ✅ Success: {success_count}/{len(raw_messages)} ({success_count / len(raw_messages) * 100:.1f}%)"
            )
            print(f"  ❌ Failed: {failed_count}")
            print(f"  ⏱️  Total time: {elapsed:.2f}s")
            print(f"  ⚡ Throughput: {throughput:.3f} msg/sec")
            print(f"  📈 Avg time per message: {avg_time:.2f}s")

            # Анализ качества
            if processed_docs:
                print("\n🔍 Quality Analysis:")

                quality_metrics = {
                    "has_summary": 0,
                    "has_topics": 0,
                    "has_entities": 0,
                    "correct_language": 0,
                    "avg_summary_len": 0,
                    "avg_topics_count": 0,
                    "avg_entities_count": 0,
                }

                # Показываем 3 примера
                for i, doc in enumerate(processed_docs[:3], 1):
                    print(f"\n  📄 Sample {i}:")
                    print(f"    Summary: {doc.summary[:100]}...")
                    print(f"    Topics: {doc.topics[:4]}")
                    print(f"    Entities: {len(doc.entities)} found")
                    print(f"    Language: {doc.language}")

                # Метрики по всем документам
                for doc in processed_docs:
                    quality_metrics["has_summary"] += (
                        1 if doc.summary and len(doc.summary) > 10 else 0
                    )
                    quality_metrics["has_topics"] += 1 if doc.topics and len(doc.topics) > 0 else 0
                    quality_metrics["has_entities"] += (
                        1 if doc.entities and len(doc.entities) > 0 else 0
                    )
                    quality_metrics["correct_language"] += 1 if doc.language == "ru" else 0
                    quality_metrics["avg_summary_len"] += len(doc.summary) if doc.summary else 0
                    quality_metrics["avg_topics_count"] += len(doc.topics) if doc.topics else 0
                    quality_metrics["avg_entities_count"] += (
                        len(doc.entities) if doc.entities else 0
                    )

                total = len(processed_docs)
                quality_metrics["avg_summary_len"] /= total
                quality_metrics["avg_topics_count"] /= total
                quality_metrics["avg_entities_count"] /= total

                print(f"\n  📊 Aggregate Quality Metrics ({total} docs):")
                print(
                    f"    Summary coverage: {quality_metrics['has_summary']}/{total} ({quality_metrics['has_summary'] / total * 100:.1f}%)"
                )
                print(
                    f"    Topics coverage: {quality_metrics['has_topics']}/{total} ({quality_metrics['has_topics'] / total * 100:.1f}%)"
                )
                print(
                    f"    Entities coverage: {quality_metrics['has_entities']}/{total} ({quality_metrics['has_entities'] / total * 100:.1f}%)"
                )
                print(
                    f"    Language accuracy: {quality_metrics['correct_language']}/{total} ({quality_metrics['correct_language'] / total * 100:.1f}%)"
                )
                print(f"    Avg summary length: {quality_metrics['avg_summary_len']:.0f} chars")
                print(f"    Avg topics per doc: {quality_metrics['avg_topics_count']:.1f}")
                print(f"    Avg entities per doc: {quality_metrics['avg_entities_count']:.1f}")

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
                print("\n❌ No documents were successfully processed")
                return None

        finally:
            await raw_session.close()
            await processing_session.close()
            if hasattr(pipeline, "llm_client") and hasattr(pipeline.llm_client, "close"):
                await pipeline.llm_client.close()
    finally:
        await db.close()


async def main():
    """Запустить тесты Anthropic и Gemini"""
    print("🚀 TG_parser v1.2.0 — Anthropic & Gemini Testing")
    print("=" * 80)
    print("\n📋 Test Configuration:")
    print("  • Message count: 10 per provider")
    print("  • Concurrency: 1 (baseline)")
    print("  • Force reprocess: Yes")
    print("  • Channel: labdiagnostica_logical")

    # Конфигурация тестов
    tests = [
        ("anthropic", "claude-sonnet-4-20250514"),  # Актуальное название модели (2025)
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
            print("\n⏸️  Waiting 5 seconds before next provider...")
            await asyncio.sleep(5)

    # Результаты
    print(f"\n{'=' * 80}")
    print("📊 SUMMARY")
    print(f"{'=' * 80}\n")

    if results:
        # Загружаем результаты OpenAI из предыдущего теста
        openai_result = None
        try:
            with open("test_results_cloud_providers.json") as f:
                previous_results = json.load(f)
                openai_result = previous_results[0] if previous_results else None
        except Exception:
            pass

        # Добавляем OpenAI к сравнению если есть
        all_results = results.copy()
        if openai_result:
            all_results.insert(0, openai_result)
            print("ℹ️  Including OpenAI results from previous test\n")

        # Performance сравнение
        print("⚡ Performance Comparison:")
        print(f"{'Provider':<15} {'Model':<30} {'Success':<10} {'Throughput':<15} {'Avg Time':<12}")
        print("-" * 85)
        for r in all_results:
            print(
                f"{r['provider']:<15} "
                f"{r['model']:<30} "
                f"{r['success_rate']:.0f}%{' ' * 6} "
                f"{r['throughput']:.3f} msg/s{' ' * 2} "
                f"{r['avg_time']:.2f}s"
            )

        # Quality сравнение
        print("\n📝 Quality Comparison:")
        print(f"{'Provider':<15} {'Summary':<12} {'Topics':<12} {'Entities':<12} {'Lang Acc':<12}")
        print("-" * 85)
        for r in all_results:
            q = r["quality"]
            total = r["success_count"]
            if total > 0:
                print(
                    f"{r['provider']:<15} "
                    f"{q['has_summary']}/{total} ({q['has_summary'] / total * 100:.0f}%){' ' * 2} "
                    f"{q['has_topics']}/{total} ({q['has_topics'] / total * 100:.0f}%){' ' * 2} "
                    f"{q['has_entities']}/{total} ({q['has_entities'] / total * 100:.0f}%){' ' * 2} "
                    f"{q['correct_language']}/{total} ({q['correct_language'] / total * 100:.0f}%)"
                )

        # Рекомендация
        print("\n💡 Recommendations:")
        best_perf = max(all_results, key=lambda x: x["throughput"])
        best_quality = max(
            all_results,
            key=lambda x: (
                (
                    x["quality"]["has_summary"]
                    + x["quality"]["has_topics"]
                    + x["quality"]["has_entities"]
                )
                if x["success_count"] > 0
                else 0
            ),
        )

        print(
            f"  🏆 Best performance: {best_perf['provider']} ({best_perf['throughput']:.3f} msg/s)"
        )
        print(f"  🏆 Best quality: {best_quality['provider']}")

        # Сохраняем полные результаты
        output_path = Path("test_results_all_cloud_providers.json")
        with open(output_path, "w") as f:
            json.dump(all_results, f, indent=2, default=str)
        print(f"\n💾 Full results saved to: {output_path}")

    else:
        print("❌ No successful tests completed")
        print("\nPossible issues:")
        print("  • Check API keys are valid")
        print("  • Check account has sufficient balance/credits")
        print("  • Check quota limits")


if __name__ == "__main__":
    asyncio.run(main())
