from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ytcore.models import IndexKaydi

# FTS5 unicode61 ile hizalı tokenizasyon (noktalama/boşlukta böler). Hem FakeIndexStore
# hem rarity df hesabı bunu kullanır → iki store AYNI token semantiği (review HIGH bigram).
_TOKEN = re.compile(r"\w+", re.UNICODE)


def _fold(s: str) -> str:
    """FTS5 unicode61 (remove_diacritics 2) case-folding eşi (review tur-3/4 MED İ/I-case).

    Deterministik: lower + NFD (CANONICAL ayrıştır) + tüm birleşen-işaretleri (combining) sök →
    tüm diakritikler düşer (İ→i, ş→s, ü→u, ğ→g). NFD (NFKD DEĞİL): FTS5 remove_diacritics 2 yalnız
    diakritik söker, compatibility-dönüşüm (ﬁ→fi, ½→1⁄2, ²→2, Ⅻ→xii) YAPMAZ — NFKD bunları
    genişletip iki store df'ini saptırırdı (tur-4 MED); NFD genişletmez → FTS5 ile birebir hizalı.
    KAPSAM (review tur-5 LOW): lower()+NFD diakritik + ligature (ﬁ→ﬁ korunur, NFKD/casefold
    açardı) + Türkçe İ-case'i FTS5 ile hizalar. Unicode *simple* case-folding'in katladığı nadir
    kod-noktaları (µ U+00B5 → μ) KAPSAM DIŞI — casefold() bunu çözerdi ama ligature'ı (ﬁ→fi)
    açıp FTS5 ile çelişirdi; FTS5 simple-fold Python'da yerleşik değil. µ/mikron TR hukuk
    metninde pratikte yok → kabul. NOT: ş/s aynı token'a katlanır (rarity ~; eşik korpus bekler).
    """
    n = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in n if not unicodedata.combining(c))


@runtime_checkable
class IndexStore(Protocol):
    def ekle(self, kayit: IndexKaydi, govde: str, vektor: list[float]) -> None: ...

    def ara(self, sorgu: str, k: int = 10) -> list[IndexKaydi]: ...

    def komsular(self, vektor: list[float], k: int, haric_id: str) -> list[float]: ...

    def terim_df(self, terim: str) -> int: ...

    def belge_sayisi(self) -> int: ...


def _benzerlik(a: list[float], b: list[float]) -> float:
    """Güvenli kosinüs (vektörler normalize olmayabilir — FakeIndexStore ham vektör)."""
    nokta = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return nokta / (na * nb)


def _govde_alani(kayit: IndexKaydi, govde: str) -> str:
    # _fold: FTS5 case-folding eşi (İ→i; ş korunur) → terim_df iki store tutarlı (review tur-3).
    return _fold(kayit.baslik + " " + govde + " " + " ".join(kayit.keywords))


def _ardisik_gecer(belge_tok: list[str], terim_tok: list[str], n: int) -> bool:
    """terim_tok, belge_tok içinde ARDIŞIK alt-dizi mi (FTS5 phrase MATCH eşi)."""
    return any(belge_tok[i : i + n] == terim_tok for i in range(len(belge_tok) - n + 1))


class FakeIndexStore:
    """Hermetik in-memory index (ağsız/torch'suz/LanceDB'siz). Test + exe selftest.

    LanceFtsRrfStore ile AYNI kontrat: ekle/ara/komsular/terim_df/belge_sayisi.
    Retrieval = saf-python kosinüs + keyword token kesişimi (RRF'le birleştirilir).
    """

    def __init__(self) -> None:
        self._kayitlar: list[tuple[IndexKaydi, str, list[float]]] = []

    def ekle(self, kayit: IndexKaydi, govde: str, vektor: list[float]) -> None:
        self._kayitlar = [r for r in self._kayitlar if r[0].video_id != kayit.video_id]
        self._kayitlar.append((kayit, govde, list(vektor)))

    def ara(self, sorgu: str, k: int = 10) -> list[IndexKaydi]:
        from ytcore.infra.rrf import rrf_birlestir

        s_token = set(_fold(sorgu).split())
        # Keyword sıralaması: token kesişim sayısına göre (anlamsal sıralama yok —
        # sorgu vektörü FakeEmbedding'siz; yalnız keyword tarafı).
        kw_sira = sorted(
            self._kayitlar,
            key=lambda r: -len(s_token & set(_govde_alani(r[0], r[1]).split())),
        )
        kw_ids = [r[0].video_id for r in kw_sira]
        birlesik = rrf_birlestir([kw_ids], k=60)
        idx = {r[0].video_id: r[0] for r in self._kayitlar}
        return [idx[vid] for vid, _ in birlesik[:k] if vid in idx]

    def komsular(self, vektor: list[float], k: int, haric_id: str) -> list[float]:
        benz = [
            _benzerlik(vektor, v) for (kayit, _, v) in self._kayitlar if kayit.video_id != haric_id
        ]
        return sorted(benz, reverse=True)[:k]

    def terim_df(self, terim: str) -> int:
        # FTS5 phrase-MATCH semantiği (review HIGH bigram regresyonu): terim'i _TOKEN ile böl;
        # çok-kelimeli (YAKE n=2 bigram 'sözleşme hukuku') terim govde token-dizisinde ARDIŞIK
        # geçiyor mu? Tek-kelime → tek-token eşleşme. \w+ noktalamayı da böler (FTS5 unicode61
        # hizalı) → LanceFtsRrfStore.terim_df ile AYNI df (eval-Fake ≠ üretim-Lance rarity yok).
        t_tok = _TOKEN.findall(_fold(terim))
        if not t_tok:
            return 0
        n = len(t_tok)
        return sum(
            1
            for (kayit, govde, _) in self._kayitlar
            if _ardisik_gecer(_TOKEN.findall(_govde_alani(kayit, govde)), t_tok, n)
        )

    def belge_sayisi(self) -> int:
        return len(self._kayitlar)


class LanceFtsRrfStore:
    """LanceDB(IVF-PQ anlamsal) + SQLite FTS5(BM25 keyword) + RRF(k=60) hibrit.

    sqlite-vec HNSW YOK (A09) → LanceDB anlamsal katman. FTS5 keyword/df (Rarity IDF).
    Tek-dosya taşınabilir korpus (output_base/_index/). torch ÇEKMEZ (Rust+pyarrow).
    """

    def __init__(self, taban: Path | None = None) -> None:
        from ytcore.config import get_config

        self._taban = taban or get_config().index_base
        self._lance_yolu = self._taban / "lance"
        self._fts_yolu = self._taban / "fts.db"
        self._taban.mkdir(parents=True, exist_ok=True)
        self._tablo: Any = None  # lazy
        self._db: Any = None

    def _baglan(self) -> Any:
        import lancedb

        if self._db is None:
            self._db = lancedb.connect(str(self._lance_yolu))
        return self._db

    def _mevcut_tablo(self) -> Any:
        """Var olan tabloyu aç (yoksa None — ilk ekleme vektör boyutuyla oluşturur)."""
        if self._tablo is not None:
            return self._tablo
        db = self._baglan()
        # list_tables() (table_names() deprecated, >=0.30) ListTablesResponse döndürür —
        # DÜZ liste DEĞİL; `.tables` şart (aksi `in` her zaman False → sessiz regresyon: ekle()
        # var olan tabloda create_table'a düşer). Empirik doğrulandı (lancedb 0.33).
        if "kayitlar" in db.list_tables().tables:
            self._tablo = db.open_table("kayitlar")
        return self._tablo

    def _tablo_olustur(self, boyut: int) -> Any:
        # LanceDB vektör araması fixed_size_list ister (variable list = vektör kolonu DEĞİL).
        # Boyut ilk eklemede belli (bge-m3=1024, FakeEmbedding=64) → lazy create.
        import pyarrow as pa

        sema = pa.schema(
            [
                pa.field("video_id", pa.string()),
                pa.field("vektor", pa.list_(pa.float32(), boyut)),
                pa.field("baslik", pa.string()),
                pa.field("govde", pa.string()),
                pa.field("keywords", pa.string()),
            ]
        )
        self._tablo = self._baglan().create_table("kayitlar", schema=sema)
        return self._tablo

    def _fts(self) -> Any:
        import sqlite3

        conn = sqlite3.connect(str(self._fts_yolu))
        # remove_diacritics 2: tüm diakritikleri sök (İ→i, ş→s, ü→u) — Python _fold (NFD+
        # combining sök) ile hizalı → iki store terim_df AYNI (review tur-3/4 MED İ-case).
        # NOT (review tur-4 LOW): CREATE IF NOT EXISTS mevcut tabloda tokenizer'ı GÜNCELLEMEZ.
        # Faz 3 taze-feature (üretim fts.db yok; testler tmp-dizin) → migrasyon gerekmez. İleride
        # şema değişirse _index/ yeniden kurulmalı (PRAGMA ile tokenizer doğrulama Faz 5).
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS belgeler USING fts5("
            "video_id UNINDEXED, baslik, keywords, govde, "
            "tokenize = 'unicode61 remove_diacritics 2')"
        )
        # Lance şemasını yerinde kırmadan generic kaynak URL/metadata'sını saklayan additive
        # katman. Eski korpuslarda tablo boş kalır ve YouTube fallback'i çalışır.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kaynak_metadata("
            "video_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        return conn

    def _vektor_boyutu(self, t: Any) -> int | None:
        # Mevcut tablonun fixed_size_list vektör boyutu (sema introspeksiyonu).
        try:
            return int(t.schema.field("vektor").type.list_size)
        except Exception:  # noqa: BLE001 — sema introspeksiyonu best-effort
            return None

    def _satir_snapshot(self, t: Any, video_id: str) -> dict[str, Any] | None:
        """Mevcut Lance satırının kopyası — atomik rollback için (yoksa None).

        Vektörsüz filtre-pushdown (search().where) tüm tabloyu yüklemez. Okuma HATA verirse
        BİLEREK yukarı fırlatır: snapshot ekle()'deki yıkıcı delete'ten ÖNCE alınır, dolayısıyla
        burada patlamak iki store'u el değmemiş (tutarlı) bırakır — sessizce None dönmek ise
        rollback'i eskisiz bırakıp desync riskini geri getirir.
        """
        satir = t.search().where(f"video_id = '{video_id}'").limit(1).to_arrow().to_pylist()
        if not satir:
            return None
        r = satir[0]
        return {
            "video_id": r["video_id"],
            "vektor": list(r["vektor"]),
            "baslik": r["baslik"],
            "govde": r["govde"],
            "keywords": r["keywords"],
        }

    def ekle(self, kayit: IndexKaydi, govde: str, vektor: list[float]) -> None:
        vek = [float(x) for x in vektor]
        t = self._mevcut_tablo()
        if t is None:
            t = self._tablo_olustur(len(vek))
        else:
            # Boyut kilidi guard (review HIGH): fake-embed(64) gerçek-index'e yazılıp sonra
            # bge-m3(1024) eklenmesin. Store-seviyesinde NET ValueError; pipeline (_output_node)
            # bunu graceful yakalar → index_eklendi=False + .md korunur (analiz çökmez —
            # ValueError KOD_HATALARI'nda DEĞİL, kasıtlı: korpus-konfig hatası tamamlanmış
            # analizi kaybettirmesin). Normalde index_al fake-embed'de FakeIndexStore döner; bu
            # son savunma hattı (değişmez #3 veri-bütünlüğü).
            mevcut = self._vektor_boyutu(t)
            if mevcut is not None and mevcut != len(vek):
                raise ValueError(
                    f"index vektör boyutu uyuşmazlığı: tablo={mevcut}, gelen={len(vek)} "
                    "(embedding modeli değişti mi? fake-embed gerçek-index'e yazılmış olabilir)"
                )
        yeni = {
            "video_id": kayit.video_id,
            "vektor": vek,
            "baslik": kayit.baslik,
            "govde": govde,
            "keywords": " ".join(kayit.keywords),
        }
        # Atomiklik (review HIGH): Lance + SQLite FTS iki AYRI store — kısmi yazım
        # belge_sayisi() ↔ terim_df desync bırakmasın. SQLite'ın "commit etme = otomatik geri
        # al" özelliği bedava rollback verir → FTS SON commit noktasıdır; yalnız Lance manuel
        # snapshot+restore gerektirir. Snapshot YIKICI delete'ten önce alınır; HERHANGİ bir
        # hatada (Lance add VEYA FTS DELETE/INSERT) Lance eski hâline döner: re-update'te eski
        # kayıt TAM korunur, yeni video_id'de tamamen geri alınır — asla yarım kalmaz.
        eski = self._satir_snapshot(t, kayit.video_id)
        t.delete(f"video_id = '{kayit.video_id}'")
        try:
            t.add([yeni])
            conn = self._fts()
            try:
                conn.execute("DELETE FROM belgeler WHERE video_id = ?", (kayit.video_id,))
                conn.execute(
                    "INSERT INTO belgeler(video_id, baslik, keywords, govde) VALUES (?,?,?,?)",
                    (kayit.video_id, kayit.baslik, " ".join(kayit.keywords), govde),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO kaynak_metadata(video_id, payload) VALUES (?, ?)",
                    (kayit.video_id, kayit.model_dump_json()),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            # Lance'i eski hâline getir: kısmi yeni satırı sil, varsa eski satırı geri ekle.
            # (FTS commit edilmediyse SQLite zaten otomatik geri aldı → iki store eski hâlde.)
            t.delete(f"video_id = '{kayit.video_id}'")
            if eski is not None:
                t.add([eski])
            raise

    def ara(self, sorgu: str, k: int = 10) -> list[IndexKaydi]:
        from ytcore.infra.embedding import embedding_al
        from ytcore.infra.rrf import rrf_birlestir

        t = self._mevcut_tablo()
        if t is None or t.count_rows() == 0:
            return []
        # Anlamsal sıralama (LanceDB vektör, kosinüs — FakeIndexStore ile aynı ölçek).
        qvek = embedding_al().embed([sorgu])[0]
        anlamsal = [
            r["video_id"]
            for r in t.search(qvek, vector_column_name="vektor")
            .metric("cosine")
            .limit(k * 2)
            .to_list()
        ]
        # Keyword sıralaması (FTS5 BM25). Token'ları tırnakla → FTS5 rezerve kelime
        # (AND/OR/NOT/NEAR) sözdizimi-hatası yapmasın (review LOW: hukuki "ve/AND" sorgusu).
        conn = self._fts()
        try:
            kelime = " OR ".join(f'"{p}"' for p in sorgu.split() if p.isalnum()) or f'"{sorgu}"'
            satir = conn.execute(
                "SELECT video_id FROM belgeler WHERE belgeler MATCH ? "
                "ORDER BY bm25(belgeler) LIMIT ?",
                (kelime, k * 2),
            ).fetchall()
        except Exception:  # noqa: BLE001 — FTS sözdizimi/boş guard (model-dışı sınır)
            satir = []
        finally:
            conn.close()
        keyword = [r[0] for r in satir]
        birlesik = rrf_birlestir([anlamsal, keyword], k=60)
        idx = {r["video_id"]: r for r in t.to_arrow().to_pylist()}
        secilen_idler = [vid for vid, _ in birlesik[:k]]
        metadata: dict[str, IndexKaydi] = {}
        if secilen_idler:
            conn = self._fts()
            try:
                yerler = ",".join("?" for _ in secilen_idler)
                for vid, payload in conn.execute(
                    f"SELECT video_id, payload FROM kaynak_metadata WHERE video_id IN ({yerler})",
                    secilen_idler,
                ).fetchall():
                    try:
                        metadata[str(vid)] = IndexKaydi.model_validate(json.loads(payload))
                    except (ValueError, TypeError):
                        continue
            finally:
                conn.close()
        cikti: list[IndexKaydi] = []
        for vid, _ in birlesik[:k]:
            if vid in metadata:
                cikti.append(metadata[vid])
                continue
            r = idx.get(vid)
            if r is not None:
                cikti.append(
                    IndexKaydi(
                        video_url=f"https://youtu.be/{vid}",
                        video_id=vid,
                        baslik=r["baslik"],
                        anadil="",
                        kanal="",
                        konu="",
                        uretici_slug="",
                        video_slug=vid,
                        analiz_tarihi="",
                        keywords=r["keywords"].split() if r["keywords"] else [],
                    )
                )
        return cikti

    def komsular(self, vektor: list[float], k: int, haric_id: str) -> list[float]:
        t = self._mevcut_tablo()
        if t is None or t.count_rows() == 0:
            return []
        sonuc = (
            t.search([float(x) for x in vektor], vector_column_name="vektor")
            .metric("cosine")
            .limit(k + 1)
            .to_list()
        )
        # LanceDB cosine _distance = 1 − kosinüs_benzerlik → benzerlik = 1 − _distance.
        # FakeIndexStore.komsular ile AYNI kosinüs ölçeği (review HIGH: novelty/niş store-tutarlı).
        benz = [1.0 - r["_distance"] for r in sonuc if r["video_id"] != haric_id]
        return benz[:k]

    def terim_df(self, terim: str) -> int:
        conn = self._fts()
        try:
            kelime = terim if terim.isalnum() else f'"{terim}"'
            satir = conn.execute(
                "SELECT count(*) FROM belgeler WHERE belgeler MATCH ?", (kelime,)
            ).fetchone()
            return int(satir[0]) if satir else 0
        except Exception:  # noqa: BLE001 — FTS sözdizimi sınırı
            return 0
        finally:
            conn.close()

    def belge_sayisi(self) -> int:
        t = self._mevcut_tablo()
        return int(t.count_rows()) if t is not None else 0


def get_index_store() -> IndexStore:
    return LanceFtsRrfStore()


def index_al() -> IndexStore:
    """YT_INDEX_FIXTURE set ise FakeIndexStore (hermetik), değilse LanceFtsRrfStore.

    NOT (review tur-4): YT_EMBED_FIXTURE'a KUPLAJLANMAZ — aksi hâlde exe selftest (YT_EMBED_FIXTURE
    =1, fixture-clean) gerçek LanceDB'yi HİÇ çalıştırmaz (frozen-exe lancedb doğrulaması kaybolur).
    fake-embed(64)→gerçek-index boyut-kilidi riski iki yerde örtülür: (1) ekle() boyut-uyuşmazlığı
    NET ValueError; (2) eval_kos YT_INDEX_FIXTURE'i açıkça set eder (üretim korpusuna yazmaz).
    """
    if os.environ.get("YT_INDEX_FIXTURE", "").strip():
        return FakeIndexStore()
    return get_index_store()
