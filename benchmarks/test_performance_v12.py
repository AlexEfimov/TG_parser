#!/usr/bin/env python3
"""
Performance тестирование v1.2.0 — Parallel processing
Тестирует влияние concurrency на производительность
"""

import asyncio
import time

from tg_parser.config import settings
from tg_parser.processing import create_processing_pipeline
from tg_parser.storage.sqlalchemy import Database, DatabaseConfig
from tg_parser.storage.sqlalchemy.processed_document_repo import SAProcessedDocumentRepo
from tg_parser.storage.sqlalchemy.processing_failure_repo import SAProcessingFailureRepo
from tg_parser.storage.sqlalchemy.raw_message_repo import SARawMessageRepo


async def test_concurrency(
    concurrency: int,
    provider: str = "ollama",
    model: str = "qwen3:8b",
    message_count: int = 20,
    channel_id: str = "labdiagnostica_logical",
):
    """Тест с заданным concurrency"""
    print(f"\n{'=' * 70}")
    print(f"⚡ Testing concurrency={concurrency}")
    print(f"{'=' * 70}\n")

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
            pipeline = create_processing_pipeline(
                provider=provider,
                model=model,
                processed_doc_repo=processed_repo,
                failure_repo=failure_repo,
            )

            # Загружаем raw сообщения
            all_raw = await raw_repo.list_by_channel(channel_id)
            if not all_raw:
                print("❌ No raw messages found")
                return None

            # Берём заданное количество
            raw_messages = all_raw[:message_count]
            print(f"📦 Processing {len(raw_messages)} messages")

            # Обработка
            start = time.time()
            processed_docs = await pipeline.process_batch(
                raw_messages,
                force=True,  # Переобработать
                concurrency=concurrency,
            )
            elapsed = time.time() - start

            # Статистика
            success_count = len(processed_docs)
            failed_count = len(raw_messages) - success_count
            avg_time = elapsed / len(raw_messages) if raw_messages else 0
            throughput = len(raw_messages) / elapsed if elapsed > 0 else 0

            print("\n📊 Results:")
            print(f"  ✅ Success: {success_count}/{len(raw_messages)}")
            print(f"  ⏱️  Total time: {elapsed:.2f}s")
            print(f"  ⚡ Throughput: {throughput:.2f} msg/sec")
            print(f"  📈 Avg time: {avg_time:.2f}s per message")

            return {
                "concurrency": concurrency,
                "message_count": len(raw_messages),
                "success_count": success_count,
                "failed_count": failed_count,
                "total_time": elapsed,
                "avg_time": avg_time,
                "throughput": throughput,
            }

        finally:
            await raw_session.close()
            await processing_session.close()
            if hasattr(pipeline, "llm_client") and hasattr(pipeline.llm_client, "close"):
                await pipeline.llm_client.close()
    finally:
        await db.close()


async def main():
    """Запустить performance тесты"""
    print("🚀 TG_parser v1.2.0 — Performance Testing")
    print("=" * 70)

    # Тесты с разным concurrency
    # Используем меньше сообщений для более быстрого теста
    message_count = 15  # 15 сообщений для теста
    concurrency_levels = [1, 3, 5]

    results = []
    baseline_time = None

    for concurrency in concurrency_levels:
        try:
            result = await test_concurrency(concurrency=concurrency, message_count=message_count)
            if result:
                results.append(result)

                # Сохраняем baseline (concurrency=1)
                if concurrency == 1:
                    baseline_time = result["total_time"]
        except Exception as e:
            print(f"\n❌ Test failed for concurrency={concurrency}: {e}")
            import traceback

            traceback.print_exc()

    # Summary с расчётом speedup
    print(f"\n{'=' * 70}")
    print("📊 PERFORMANCE SUMMARY")
    print(f"{'=' * 70}\n")
    print(f"{'Concurrency':<12} {'Time':<10} {'Throughput':<15} {'Speedup':<10}")
    print("-" * 70)

    for r in results:
        speedup = baseline_time / r["total_time"] if baseline_time and baseline_time > 0 else 1.0
        print(
            f"{r['concurrency']:<12} "
            f"{r['total_time']:.2f}s{' ':<5} "
            f"{r['throughput']:.2f} msg/s{' ':<5} "
            f"{speedup:.2f}x"
        )

    # Рекомендация
    print("\n💡 Рекомендация:")
    if len(results) >= 2:
        best = max(results, key=lambda x: x["throughput"])
        print(f"   Оптимальный concurrency: {best['concurrency']}")
        print(f"   Throughput: {best['throughput']:.2f} msg/sec")


if __name__ == "__main__":
    asyncio.run(main())
