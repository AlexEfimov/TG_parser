"""
Single definition of a soft-deleted channel (BUG-107).

Soft-delete lives only in ``sources.deleted_at``; ``topic_cards``,
``processed_documents`` and ``document_embeddings`` carry channel ids but no
link to that column. Every read that must not see a removed channel builds
its predicate from this module instead of re-deriving it, so a new consumer
cannot quietly pick a different meaning.

A channel is **deleted** when it has a ``sources`` row with ``deleted_at`` set
and no live row with the same ``channel_id`` (``channel_id`` is not unique —
``source_id`` is the primary key). A channel with no ``sources`` row at all is
**not** deleted: the predicate hides removed channels, it does not require a
registration.

The three ingestion / raw / processing engines point at the same database
(``create_engine_from_settings`` builds all three from ``settings.db_name``),
so a processing-session query may reference ``sources`` directly — the same
join ``workspace_repo.list_channel_ids`` already relies on.
"""

LIVE_CHANNEL_IDS_SQL = (
    "SELECT DISTINCT channel_id FROM sources WHERE deleted_at IS NULL ORDER BY channel_id"
)


def channel_is_deleted_sql(column: str) -> str:
    """SQL boolean: the channel id in ``column`` belongs to a soft-deleted channel.

    ``column`` must be table-qualified (``processed_documents.channel_id``):
    a bare ``channel_id`` would bind to ``sources.channel_id`` inside the
    subquery and make the predicate compare the table with itself.
    """
    return (
        "EXISTS (SELECT 1 FROM sources sd "
        f"WHERE sd.channel_id = {column} AND sd.deleted_at IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM sources sl "
        f"WHERE sl.channel_id = {column} AND sl.deleted_at IS NULL))"
    )


def topic_card_visible_sql(sources_column: str = "topic_cards.sources_json") -> str:
    """SQL boolean: a topic card still has at least one source that is not deleted.

    Mirrors ``assert_topic_access`` — a card spanning several channels stays
    visible while any of them is. A card with no sources is kept, as
    ``list_all`` always kept it. ``sources_json`` is ``TEXT``, hence the cast.
    """
    sources = f"COALESCE({sources_column}, '[]')::jsonb"
    return (
        f"(jsonb_array_length({sources}) = 0 OR EXISTS ("
        f"SELECT 1 FROM jsonb_array_elements_text({sources}) AS src(channel_id) "
        f"WHERE NOT {channel_is_deleted_sql('src.channel_id')}))"
    )
