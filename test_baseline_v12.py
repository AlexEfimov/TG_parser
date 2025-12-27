#!/usr/bin/env python3
"""
Baseline тестирование v1.2.0 — Multi-LLM providers
Тестирует каждый провайдер на небольшом батче сообщений
"""
import asyncio
import time
from pathlib import Path

from tg_parser.config import settings
from tg_parser.processing import create_processing_pipeline
from tg_parser.storage.sqlite import Database, DatabaseConfig
from tg_parser.storage.sqlite.processed_document_repo import SQLiteProcessedDocumentRepo
from tg_parser.storage.sqlite.processing_failure_repo import SQLiteProcessingFailureRepo
from tg_parser.storage.sqlite.raw_message_repo import SQLiteRawMessageRepo


async def test_provider(
    provider: str,
    model: str,
    limit: int = 10,
    channel_id: str = "labdiagnostica_logical"
):
    """Тест одного провайдера на limit сообщениях"""
    print(f"\n{'='*70}")
    print(f"🧪 Testing {provider.upper()} ({model})")
    print(f"{'='*70}\n")
    
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
                print(f"❌ No raw messages found for channel {channel_id}")
                return None
            
            # Берём только первые limit
            raw_messages = all_raw[:limit]
            print(f"📦 Loaded {len(raw_messages)} raw messages (из {len(all_raw)} доступных)")
            
            # Обработка
            start = time.time()
            processed_docs = await pipeline.process_batch(
                raw_messages,
                force=True,  # Переобработать
                concurrency=1  # Последовательно для baseline
            )
            elapsed = time.time() - start
            
            # Статистика
            success_count = len(processed_docs)
            failed_count = len(raw_messages) - success_count
            avg_time = elapsed / len(raw_messages) if raw_messages else 0
            
            print(f"\n📊 Results:")
            print(f"  ✅ Success: {success_count}/{len(raw_messages)} ({success_count/len(raw_messages)*100:.1f}%)")
            print(f"  ❌ Failed: {failed_count}")
            print(f"  ⏱️  Total time: {elapsed:.2f}s")
            print(f"  ⚡ Avg time: {avg_time:.2f}s per message")
            
            # Проверка качества первого документа
            if processed_docs:
                doc = processed_docs[0]
                print(f"\n🔍 Quality Check (first document):")
                print(f"  Summary: {doc.summary[:100]}...")
                print(f"  Topics: {doc.topics}")
                print(f"  Language: {doc.language}")
                print(f"  Entities count: {len(doc.entities)}")
            
            return {
                "provider": provider,
                "model": model,
                "success_count": success_count,
                "failed_count": failed_count,
                "total_time": elapsed,
                "avg_time": avg_time,
                "success_rate": success_count / len(raw_messages) * 100,
            }
            
        finally:
            await raw_session.close()
            await processing_session.close()
            if hasattr(pipeline, "llm_client") and hasattr(pipeline.llm_client, "close"):
                await pipeline.llm_client.close()
    finally:
        await db.close()


async def main():
    """Запустить все baseline тесты"""
    print("🚀 TG_parser v1.2.0 — Baseline Testing")
    print("=" * 70)
    
    # Тесты
    tests = [
        # ("openai", "gpt-4o-mini"),  # Закомментировано: требует API key
        # ("anthropic", "claude-3-5-sonnet-20241022"),  # Требует API key
        ("ollama", "qwen3:8b"),
    ]
    
    results = []
    for provider, model in tests:
        try:
            result = await test_provider(provider, model, limit=10)
            if result:
                results.append(result)
        except Exception as e:
            print(f"\n❌ Test failed for {provider}: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print(f"\n{'='*70}")
    print("📊 SUMMARY")
    print(f"{'='*70}\n")
    
    for r in results:
        print(f"{r['provider'].upper()} ({r['model']}):")
        print(f"  Success rate: {r['success_rate']:.1f}%")
        print(f"  Avg time: {r['avg_time']:.2f}s/msg")
        print()


if __name__ == "__main__":
    asyncio.run(main())

