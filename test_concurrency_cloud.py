#!/usr/bin/env python3
"""
Cloud Providers Concurrency Test для v1.2.0
Тестирует влияние concurrency на производительность облачных LLM
(OpenAI, Anthropic, Gemini)
"""
import asyncio
import time
import json
from pathlib import Path

from tg_parser.config import settings
from tg_parser.processing import create_processing_pipeline
from tg_parser.storage.sqlite import Database, DatabaseConfig
from tg_parser.storage.sqlite.processed_document_repo import SQLiteProcessedDocumentRepo
from tg_parser.storage.sqlite.processing_failure_repo import SQLiteProcessingFailureRepo
from tg_parser.storage.sqlite.raw_message_repo import SQLiteRawMessageRepo


async def test_provider_concurrency(
    provider: str,
    model: str,
    concurrency_levels: list[int] = [1, 3, 5],
    message_count: int = 15,
    channel_id: str = "labdiagnostica_logical"
):
    """Тест одного провайдера с разными уровнями concurrency"""
    print(f"\n{'='*80}")
    print(f"🧪 Testing {provider.upper()} - {model}")
    print(f"   Concurrency levels: {concurrency_levels}")
    print(f"{'='*80}\n")
    
    provider_results = []
    baseline_time = None
    
    for concurrency in concurrency_levels:
        print(f"\n⚡ Testing concurrency={concurrency}")
        print("-" * 80)
        
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
                raw_repo = SQLiteRawMessageRepo(raw_session)
                processed_repo = SQLiteProcessedDocumentRepo(processing_session)
                failure_repo = SQLiteProcessingFailureRepo(processing_session)
                
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
                    print(f"❌ No raw messages found")
                    continue
                
                raw_messages = all_raw[:message_count]
                print(f"📦 Processing {len(raw_messages)} messages")
                
                # Обработка
                start = time.time()
                processed_docs = await pipeline.process_batch(
                    raw_messages,
                    force=True,
                    concurrency=concurrency
                )
                elapsed = time.time() - start
                
                # Статистика
                success_count = len(processed_docs)
                failed_count = len(raw_messages) - success_count
                throughput = len(raw_messages) / elapsed if elapsed > 0 else 0
                
                # Сохраняем baseline
                if concurrency == concurrency_levels[0]:
                    baseline_time = elapsed
                
                speedup = baseline_time / elapsed if baseline_time and elapsed > 0 else 1.0
                
                print(f"  ✅ Success: {success_count}/{len(raw_messages)} ({success_count/len(raw_messages)*100:.1f}%)")
                print(f"  ⏱️  Total time: {elapsed:.2f}s")
                print(f"  ⚡ Throughput: {throughput:.3f} msg/sec")
                print(f"  📈 Speedup: {speedup:.2f}x")
                
                provider_results.append({
                    "concurrency": concurrency,
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "total_time": elapsed,
                    "throughput": throughput,
                    "speedup": speedup,
                })
                
            finally:
                await raw_session.close()
                await processing_session.close()
                if hasattr(pipeline, "llm_client") and hasattr(pipeline.llm_client, "close"):
                    await pipeline.llm_client.close()
        finally:
            await db.close()
        
        # Пауза между тестами
        if concurrency != concurrency_levels[-1]:
            print(f"\n⏸️  Waiting 3 seconds before next concurrency level...")
            await asyncio.sleep(3)
    
    return {
        "provider": provider,
        "model": model,
        "results": provider_results
    }


async def main():
    """Запустить concurrency тесты для всех провайдеров"""
    print("🚀 TG_parser v1.2.0 — Cloud Providers Concurrency Testing")
    print("=" * 80)
    print("\n📋 Test Configuration:")
    print("  • Message count: 15 per test")
    print("  • Concurrency levels: [1, 3, 5]")
    print("  • Force reprocess: Yes")
    print("  • Providers: OpenAI, Anthropic, Gemini")
    
    # Конфигурация тестов
    providers = [
        ("openai", "gpt-4o-mini"),
        ("anthropic", "claude-3-5-sonnet-20241022"),
        ("gemini", "gemini-2.0-flash-exp"),
    ]
    
    all_results = []
    
    for provider, model in providers:
        try:
            result = await test_provider_concurrency(
                provider, 
                model,
                concurrency_levels=[1, 3, 5],
                message_count=15
            )
            all_results.append(result)
        except Exception as e:
            print(f"\n❌ Test failed for {provider}: {e}")
            import traceback
            traceback.print_exc()
        
        # Пауза между провайдерами
        if provider != providers[-1][0]:
            print(f"\n⏸️  Waiting 10 seconds before next provider...")
            await asyncio.sleep(10)
    
    # Сравнительная таблица
    print(f"\n{'='*80}")
    print("📊 CONCURRENCY COMPARISON")
    print(f"{'='*80}\n")
    
    for provider_data in all_results:
        print(f"\n🔹 {provider_data['provider'].upper()} ({provider_data['model']})")
        print(f"{'Concurrency':<15} {'Time':<12} {'Throughput':<18} {'Speedup':<12}")
        print("-" * 80)
        
        for r in provider_data['results']:
            print(
                f"{r['concurrency']:<15} "
                f"{r['total_time']:.2f}s{' '*6} "
                f"{r['throughput']:.3f} msg/s{' '*6} "
                f"{r['speedup']:.2f}x"
            )
    
    # Рекомендации
    print(f"\n💡 Optimal Concurrency Recommendations:")
    for provider_data in all_results:
        if provider_data['results']:
            best = max(provider_data['results'], key=lambda x: x['throughput'])
            print(f"  • {provider_data['provider']}: concurrency={best['concurrency']} (throughput: {best['throughput']:.3f} msg/s)")
    
    # Сохраняем результаты
    output_path = Path("test_results_concurrency.json")
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n💾 Results saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())

