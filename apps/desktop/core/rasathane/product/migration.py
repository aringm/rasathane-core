from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from rasathane.product.store import ProductStore, digest, json_text


def read_radar_postgres(connect: Callable[[], Any]) -> dict[str, Any]:
    """Operatör tarafından verilen DB-API connection ile yalnız SELECT snapshot.

    Desktop ürününde PostgreSQL driver/Docker yoktur. Geçiş aracı mevcut Radar
    ortamındaki connector'ı verir. DSN veya parola export'a/log'a konmaz.
    Repeatable-read snapshot kaynak DB'yi değiştirmez ve tutarlı tablo sayıları verir.
    """
    connection = connect()
    try:
        connection.set_session(readonly=True, isolation_level="REPEATABLE READ", autocommit=False)
        with connection.cursor() as cursor:
            payload: dict[str, Any] = {"schema_version": 1}
            for table, fields in (
                (
                    "sources",
                    "id,name,url,type,category,enabled,is_user_disabled,"
                    "fetch_interval_minutes,metadata",
                ),
                ("articles", "id,source_id,title,url,summary,summary_tr_short,published_at"),
                ("library_items", "id,item_type,snapshot_md,snapshot_meta,note,saved_at"),
            ):
                cursor.execute(f"SELECT {fields} FROM {table} ORDER BY id")
                names = [column[0] for column in cursor.description]
                payload[table] = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        # UUID/datetime'nin taşınabilir JSON karşılığı; source SQL metadata JSON kalır.
        portable: dict[str, Any] = json.loads(json_text(payload))
        return portable
    finally:
        connection.rollback()
        connection.close()


def import_radar_snapshot(store: ProductStore, snapshot: dict[str, Any]) -> dict[str, Any]:
    fingerprint = digest(json_text(snapshot))
    result = store.import_snapshot(snapshot, fingerprint, "radar-postgres-readonly-v1")
    return {**result, "source_sha256": fingerprint, "destination": str(store.path)}
