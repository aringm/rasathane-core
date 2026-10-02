"""Rasathane için güvenli, ortak kaynak edinim sözleşmesi.

Bu modül kaynaklara özgü HTTP edinimini tek bir normalize belge modeline çevirir.
YouTube mevcut ``ytcore`` pipeline'ında kalır; ortak giriş bu ayrımı typed hata ile
görünür kılar.
"""

from __future__ import annotations

import codecs
import hashlib
import ipaddress
import json
import os
import re
import socket
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any
from urllib.parse import SplitResult, quote, unquote, urljoin, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field

_MAKSIMUM_YANIT_BYTE = 2_000_000
_ISTEK_ZAMAN_ASIMI_SN = 20.0
_KULLANICI_ARACISI = "Rasathane/0.1 (+yerel kaynak analizi)"
_GITHUB_PARCA = re.compile(r"^[A-Za-z0-9_.-]+$")
_ARXIV_KIMLIGI = re.compile(r"^(?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})(?:v\d+)?$")
_REDDIT_KIMLIGI = re.compile(r"^[A-Za-z0-9]+$")


class KaynakTuru(StrEnum):
    """Rasathane'nin doğrudan tanıdığı kaynak aileleri."""

    youtube = "youtube"
    github = "github"
    arxiv = "arxiv"
    reddit = "reddit"
    huggingface = "huggingface"
    web = "web"


class KaynakSinyali(BaseModel):
    """Kaynağa ait açıklanabilir tek değerlendirme sinyali."""

    etiket: str
    deger: str | int | float | bool | None
    aciklama: str
    durum: str


class KaynakBelgesi(BaseModel):
    """Tüm kaynak adapterlarının ürettiği normalize belge."""

    tur: KaynakTuru
    kimlik: str
    kanonik_url: str
    baslik: str
    sahip: str | None = None
    yayin_tarihi: str | None = None
    guncelleme_tarihi: str | None = None
    dil: str | None = None
    metin: str = ""
    etiketler: list[str] = Field(default_factory=list)
    metrikler: dict[str, int | float] = Field(default_factory=dict)
    ozel: dict[str, Any] = Field(default_factory=dict)
    sinyaller: list[KaynakSinyali] = Field(default_factory=list)
    edinim_durumu: str = "tam"


class KaynakHatasi(Exception):
    """Kullanıcı ve entegrasyon katmanının kodla ayırt edebildiği kaynak hatası."""

    def __init__(self, kod: str, mesaj: str) -> None:
        self.kod = kod
        self.mesaj = mesaj
        super().__init__(mesaj)


def _charset(deger: str) -> str | None:
    eslesme = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", deger, re.I)
    return eslesme.group(1) if eslesme else None


class _HTMLKodlamaAyristirici(HTMLParser):
    """Yalnız sınırlı HTML ön ekindeki gerçek meta etiketlerini oku."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.kodlama: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta" or self.kodlama:
            return
        nitelikler = {ad.lower(): (deger or "") for ad, deger in attrs}
        kodlama = nitelikler.get("charset", "").strip()
        if not kodlama and nitelikler.get("http-equiv", "").lower() == "content-type":
            kodlama = _charset(nitelikler.get("content", "")) or ""
        self.kodlama = kodlama or None


@dataclass(frozen=True)
class _Yanit:
    durum: int
    basliklar: Mapping[str, str]
    icerik: bytes

    def kodlama(self) -> tuple[str, str]:
        # BOM açık byte imzasıdır. HTTP charset, HTML meta'dan önceliklidir.
        for imza, bom_kodlama in (
            (codecs.BOM_UTF32_LE, "utf-32"),
            (codecs.BOM_UTF32_BE, "utf-32"),
            (codecs.BOM_UTF8, "utf-8-sig"),
            (codecs.BOM_UTF16_LE, "utf-16"),
            (codecs.BOM_UTF16_BE, "utf-16"),
        ):
            if self.icerik.startswith(imza):
                return bom_kodlama, "bom"
        content_type = self.basliklar.get("content-type", "")
        kodlama = _charset(content_type)
        koken = "http_charset" if kodlama else "utf8_default"
        if not kodlama and (
            "html" in content_type.lower()
            or self.icerik.lstrip()[:100].lower().startswith((b"<!doctype html", b"<html"))
        ):
            ayristirici = _HTMLKodlamaAyristirici()
            try:
                # Latin-1 burada yalnız ASCII meta niteliklerinin kayıpsız taşıyıcısıdır;
                # belge bu kodlamayla okunmaz. Gövdenin tamamında kodlama araması yapılmaz.
                ayristirici.feed(self.icerik[:8192].decode("latin-1"))
                ayristirici.close()
            except (ValueError, AssertionError) as exc:
                raise KaynakHatasi("kodlama_hatasi", "HTML kodlama bildirimi okunamadı.") from exc
            kodlama = ayristirici.kodlama
            if kodlama:
                koken = "html_meta"
        try:
            return codecs.lookup(kodlama or "utf-8").name, koken
        except LookupError as exc:
            raise KaynakHatasi(
                "kodlama_hatasi", "Kaynağın bildirdiği karakter kodlaması desteklenmiyor."
            ) from exc

    def metin(self) -> str:
        kodlama, _ = self.kodlama()
        try:
            metin = self.icerik.decode(kodlama, errors="strict")
        except (UnicodeError, LookupError) as exc:
            raise KaynakHatasi(
                "kodlama_hatasi", "Kaynak metni bildirilen karakter kodlamasıyla okunamadı."
            ) from exc
        if "\ufffd" in metin:
            raise KaynakHatasi(
                "kodlama_hatasi", "Kaynakta bozulmuş karakterler bulundu; analiz başlatılmadı."
            )
        return metin

    def json(self) -> Any:
        try:
            return json.loads(self.icerik.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KaynakHatasi(
                "yanit_gecersiz", "Kaynak geçerli bir JSON yanıtı döndürmedi."
            ) from exc


def _normalize_metin(deger: Any) -> str:
    if not isinstance(deger, str):
        return ""
    return " ".join(deger.split())


def _alan_metin(veri: Mapping[str, Any], anahtar: str) -> str | None:
    deger = veri.get(anahtar)
    if not isinstance(deger, str):
        return None
    temiz = _normalize_metin(deger)
    return temiz or None


def _alan_sayi(veri: Mapping[str, Any], anahtar: str) -> int | float | None:
    deger = veri.get(anahtar)
    if isinstance(deger, bool) or not isinstance(deger, (int, float)):
        return None
    return deger


def _alan_nesne(veri: Mapping[str, Any], anahtar: str) -> Mapping[str, Any]:
    deger = veri.get(anahtar)
    if not isinstance(deger, dict):
        return {}
    return deger


def _liste_metin(deger: Any) -> list[str]:
    if not isinstance(deger, list):
        return []
    sonuc: list[str] = []
    for oge in deger:
        if isinstance(oge, str):
            temiz = _normalize_metin(oge)
            if temiz and temiz not in sonuc:
                sonuc.append(temiz)
    return sonuc


def _url_ayristir(url: str) -> SplitResult:
    if not isinstance(url, str) or not url.strip():
        raise KaynakHatasi("gecersiz_url", "Kaynak URL'si boş olamaz.")
    temiz_url = url.strip()
    try:
        parcalar = urlsplit(temiz_url)
    except ValueError as exc:
        raise KaynakHatasi("gecersiz_url", "Kaynak URL'si geçerli değil.") from exc
    if parcalar.scheme.lower() not in {"http", "https"}:
        raise KaynakHatasi(
            "desteklenmeyen_protokol", "Yalnız http ve https kaynakları desteklenir."
        )
    if parcalar.username is not None or parcalar.password is not None:
        raise KaynakHatasi(
            "kimlik_bilgisi_yasak", "URL içinde kullanıcı adı veya parola kullanılamaz."
        )
    try:
        host = parcalar.hostname
        _ = parcalar.port
    except ValueError as exc:
        raise KaynakHatasi("gecersiz_url", "Kaynak URL'sindeki host veya port geçersiz.") from exc
    if not host:
        raise KaynakHatasi("gecersiz_url", "Kaynak URL'sinde host bulunamadı.")
    host = host.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise KaynakHatasi(
            "guvensiz_hedef", "Yerel veya özel ağ adreslerine kaynak isteği yapılamaz."
        )
    if "%" in host:
        raise KaynakHatasi("guvensiz_hedef", "Kapsam kimlikli IP adresleri desteklenmez.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise KaynakHatasi("guvensiz_hedef", "Yerel, ayrılmış veya özel IP adreslerine erişilemez.")
    return parcalar


def _host_eslesir(host: str, alan: str) -> bool:
    return host == alan or host.endswith(f".{alan}")


def kaynak_turu_bul(url: str) -> KaynakTuru:
    """URL'yi güvenli biçimde ayrıştırıp uygun kaynak ailesini döndürür."""

    parcalar = _url_ayristir(url)
    host = (parcalar.hostname or "").rstrip(".").lower()
    if host == "youtu.be" or _host_eslesir(host, "youtube.com"):
        return KaynakTuru.youtube
    if _host_eslesir(host, "github.com"):
        return KaynakTuru.github
    if _host_eslesir(host, "arxiv.org"):
        return KaynakTuru.arxiv
    if host == "redd.it" or _host_eslesir(host, "reddit.com"):
        return KaynakTuru.reddit
    if host == "hf.co" or _host_eslesir(host, "huggingface.co"):
        return KaynakTuru.huggingface
    return KaynakTuru.web


def _dns_guvenli(parcalar: SplitResult) -> None:
    host = parcalar.hostname
    if not host:
        raise KaynakHatasi("gecersiz_url", "Kaynak URL'sinde host bulunamadı.")
    port = parcalar.port or (443 if parcalar.scheme.lower() == "https" else 80)
    try:
        sonuclar = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise KaynakHatasi(
            "adres_cozulemedi", "Kaynak adresinin DNS çözümlemesi yapılamadı."
        ) from exc
    if not sonuclar:
        raise KaynakHatasi("adres_cozulemedi", "Kaynak adresi bir IP'ye çözümlenemedi.")
    for sonuc in sonuclar:
        sockaddr = sonuc[4]
        if not sockaddr:
            continue
        try:
            ip = ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0])
        except ValueError as exc:
            raise KaynakHatasi("guvensiz_hedef", "Kaynak IP adresi doğrulanamadı.") from exc
        if not ip.is_global:
            raise KaynakHatasi(
                "guvensiz_hedef", "Kaynak host özel, yerel veya ayrılmış bir IP'ye çözümlendi."
            )


def _istek(
    client: httpx.Client,
    url: str,
    *,
    basliklar: Mapping[str, str] | None = None,
    izinli_durumlar: set[int] | None = None,
) -> _Yanit:
    parcalar = _url_ayristir(url)
    _dns_guvenli(parcalar)
    headers = {"user-agent": _KULLANICI_ARACISI, **dict(basliklar or {})}
    try:
        with client.stream(
            "GET",
            url,
            headers=headers,
            follow_redirects=False,
            timeout=_ISTEK_ZAMAN_ASIMI_SN,
        ) as response:
            durum = response.status_code
            if 300 <= durum < 400:
                raise KaynakHatasi(
                    "yonlendirme_engellendi",
                    "Kaynağın yönlendirme yanıtı güvenlik nedeniyle otomatik izlenmedi.",
                )
            izinli = izinli_durumlar or set()
            if durum not in izinli and durum >= 400:
                if durum in {401, 403}:
                    kod = "erisim_reddedildi"
                    mesaj = "Kaynak erişim izni vermedi."
                elif durum == 404:
                    kod = "bulunamadi"
                    mesaj = "Kaynak bulunamadı."
                elif durum == 429:
                    kod = "hiz_siniri"
                    mesaj = "Kaynak istek hızını sınırladı; daha sonra yeniden deneyin."
                else:
                    kod = "uzak_sunucu_hatasi"
                    mesaj = f"Kaynak sunucusu HTTP {durum} yanıtı verdi."
                raise KaynakHatasi(kod, mesaj)
            uzunluk = response.headers.get("content-length")
            if uzunluk:
                try:
                    if int(uzunluk) > _MAKSIMUM_YANIT_BYTE:
                        raise KaynakHatasi(
                            "yanit_cok_buyuk", "Kaynak yanıtı izin verilen boyutu aşıyor."
                        )
                except ValueError:
                    pass
            icerik = bytearray()
            for parca in response.iter_bytes():
                icerik.extend(parca)
                if len(icerik) > _MAKSIMUM_YANIT_BYTE:
                    raise KaynakHatasi(
                        "yanit_cok_buyuk", "Kaynak yanıtı izin verilen boyutu aşıyor."
                    )
            return _Yanit(durum, dict(response.headers), bytes(icerik))
    except KaynakHatasi:
        raise
    except httpx.TimeoutException as exc:
        raise KaynakHatasi("zaman_asimi", "Kaynak isteği zaman aşımına uğradı.") from exc
    except httpx.RequestError as exc:
        raise KaynakHatasi("ag_hatasi", "Kaynak isteği tamamlanamadı.") from exc


def _json_nesnesi(yanit: _Yanit) -> dict[str, Any]:
    veri = yanit.json()
    if not isinstance(veri, dict):
        raise KaynakHatasi("yanit_gecersiz", "Kaynak JSON yanıtı nesne biçiminde değil.")
    return veri


def _kanonik_url_sec(aday: Any, varsayilan: str) -> str:
    if not isinstance(aday, str) or not aday.strip():
        return varsayilan
    birlesik = urljoin(varsayilan, aday.strip())
    try:
        parcalar = _url_ayristir(birlesik)
    except KaynakHatasi:
        return varsayilan
    return urlunsplit((parcalar.scheme, parcalar.netloc, parcalar.path, parcalar.query, ""))


def _github_kimligi(url: str) -> tuple[str, str]:
    parcalar = _url_ayristir(url)
    bolumler = [unquote(parca) for parca in parcalar.path.split("/") if parca]
    if (parcalar.hostname or "").lower() == "api.github.com" and bolumler[:1] == ["repos"]:
        bolumler = bolumler[1:]
    if len(bolumler) < 2:
        raise KaynakHatasi(
            "gecersiz_github_url", "GitHub URL'si bir sahip ve depo adı içermelidir."
        )
    sahip, depo = bolumler[0], bolumler[1]
    if depo.endswith(".git"):
        depo = depo[:-4]
    if (
        not sahip
        or not depo
        or not _GITHUB_PARCA.fullmatch(sahip)
        or not _GITHUB_PARCA.fullmatch(depo)
    ):
        raise KaynakHatasi("gecersiz_github_url", "GitHub sahip veya depo adı geçerli değil.")
    return sahip, depo


def _github_edin(url: str, client: httpx.Client) -> KaynakBelgesi:
    sahip, depo = _github_kimligi(url)
    kimlik = f"{sahip}/{depo}"
    kodlu_kimlik = f"{quote(sahip, safe='')}/{quote(depo, safe='')}"
    api_url = f"https://api.github.com/repos/{kodlu_kimlik}"
    github_headers = {"accept": "application/vnd.github+json"}
    if token := os.environ.get("GITHUB_TOKEN", "").strip():
        github_headers["authorization"] = f"Bearer {token}"
    api = _json_nesnesi(_istek(client, api_url, basliklar=github_headers))
    readme_headers = {**github_headers, "accept": "application/vnd.github.raw+json"}
    readme_yaniti = _istek(
        client,
        f"{api_url}/readme",
        basliklar=readme_headers,
        izinli_durumlar={404},
    )
    readme = _normalize_metin(readme_yaniti.metin()) if readme_yaniti.durum == 200 else ""
    aciklama = _alan_metin(api, "description") or ""
    metin = "\n\n".join(parca for parca in (aciklama, readme) if parca)
    owner = _alan_nesne(api, "owner")
    sahip_adi = _alan_metin(owner, "login") or sahip
    tam_ad = _alan_metin(api, "full_name") or kimlik
    metrik_adlari = {
        "yildiz": "stargazers_count",
        "fork": "forks_count",
        "acik_konu": "open_issues_count",
        "izleyen": "subscribers_count",
    }
    metrikler = {
        ad: deger
        for ad, kaynak_ad in metrik_adlari.items()
        if (deger := _alan_sayi(api, kaynak_ad)) is not None
    }
    lisans = _alan_nesne(api, "license")
    yildiz = _alan_sayi(api, "stargazers_count")
    sinyaller = []
    if yildiz is not None:
        sinyaller.append(
            KaynakSinyali(
                etiket="github_yildiz",
                deger=yildiz,
                aciklama="Deponun GitHub yıldız sayısı.",
                durum="bilgi",
            )
        )
    varsayilan_url = f"https://github.com/{quote(sahip)}/{quote(depo)}"
    return KaynakBelgesi(
        tur=KaynakTuru.github,
        kimlik=tam_ad,
        kanonik_url=_kanonik_url_sec(api.get("html_url"), varsayilan_url),
        baslik=tam_ad,
        sahip=sahip_adi,
        yayin_tarihi=_alan_metin(api, "created_at"),
        guncelleme_tarihi=_alan_metin(api, "pushed_at") or _alan_metin(api, "updated_at"),
        dil=None,
        metin=metin,
        etiketler=_liste_metin(api.get("topics")),
        metrikler=metrikler,
        ozel={
            "github_id": api.get("id"),
            "programlama_dili": _alan_metin(api, "language"),
            "varsayilan_dal": _alan_metin(api, "default_branch"),
            "lisans": _alan_metin(lisans, "spdx_id"),
            "arsivlenmis": bool(api.get("archived", False)),
            "fork_depo": bool(api.get("fork", False)),
            "gorunurluk": _alan_metin(api, "visibility"),
        },
        sinyaller=sinyaller,
        edinim_durumu="tam" if readme else "kismi",
    )


def _arxiv_kimligi(url: str) -> str:
    parcalar = _url_ayristir(url)
    yol = unquote(parcalar.path).strip("/")
    for onek in ("abs/", "pdf/"):
        if yol.startswith(onek):
            yol = yol[len(onek) :]
            break
    if yol.endswith(".pdf"):
        yol = yol[:-4]
    if not _ARXIV_KIMLIGI.fullmatch(yol):
        raise KaynakHatasi("gecersiz_arxiv_url", "arXiv URL'sinde geçerli bir yayın kimliği yok.")
    return yol


def _xml_metin(kok: ET.Element, yol: str, ns: dict[str, str]) -> str | None:
    oge = kok.find(yol, ns)
    if oge is None:
        return None
    temiz = _normalize_metin(oge.text)
    return temiz or None


def _arxiv_edin(url: str, client: httpx.Client) -> KaynakBelgesi:
    istenen_kimlik = _arxiv_kimligi(url)
    api_url = f"https://export.arxiv.org/api/query?id_list={quote(istenen_kimlik, safe='')}"
    yanit = _istek(client, api_url, basliklar={"accept": "application/atom+xml"})
    try:
        kok = ET.fromstring(yanit.icerik)
    except ET.ParseError as exc:
        raise KaynakHatasi("yanit_gecersiz", "arXiv geçerli bir Atom yanıtı döndürmedi.") from exc
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    entry = kok.find("atom:entry", ns)
    if entry is None:
        raise KaynakHatasi("bulunamadi", "arXiv yayını bulunamadı.")
    entry_url = _xml_metin(entry, "atom:id", ns)
    kimlik = istenen_kimlik
    if entry_url:
        aday = entry_url.rsplit("/abs/", 1)[-1]
        if _ARXIV_KIMLIGI.fullmatch(aday):
            kimlik = aday
    yazarlar = [
        ad
        for yazar in entry.findall("atom:author", ns)
        if (ad := _xml_metin(yazar, "atom:name", ns))
    ]
    kategoriler = [
        terim
        for kategori in entry.findall("atom:category", ns)
        if (terim := _normalize_metin(kategori.attrib.get("term")))
    ]
    alternatif_url: str | None = None
    pdf_url: str | None = None
    for link in entry.findall("atom:link", ns):
        if link.attrib.get("rel") == "alternate":
            alternatif_url = link.attrib.get("href")
        if link.attrib.get("title") == "pdf":
            pdf_url = link.attrib.get("href")
    varsayilan_url = f"https://arxiv.org/abs/{quote(kimlik, safe='/')}"
    return KaynakBelgesi(
        tur=KaynakTuru.arxiv,
        kimlik=kimlik,
        kanonik_url=_kanonik_url_sec(alternatif_url or entry_url, varsayilan_url),
        baslik=_xml_metin(entry, "atom:title", ns) or kimlik,
        sahip=", ".join(yazarlar) or None,
        yayin_tarihi=_xml_metin(entry, "atom:published", ns),
        guncelleme_tarihi=_xml_metin(entry, "atom:updated", ns),
        dil="en",
        metin=_xml_metin(entry, "atom:summary", ns) or "",
        etiketler=kategoriler,
        metrikler={"yazar_sayisi": len(yazarlar), "kategori_sayisi": len(kategoriler)},
        ozel={
            "yazarlar": yazarlar,
            "pdf_url": _kanonik_url_sec(pdf_url, varsayilan_url) if pdf_url else None,
            "doi": _xml_metin(entry, "arxiv:doi", ns),
            "yorum": _xml_metin(entry, "arxiv:comment", ns),
            "dergi_referansi": _xml_metin(entry, "arxiv:journal_ref", ns),
        },
        sinyaller=[
            KaynakSinyali(
                etiket="surum",
                deger=kimlik.rsplit("v", 1)[-1] if re.search(r"v\d+$", kimlik) else 1,
                aciklama="arXiv yayın sürümü.",
                durum="bilgi",
            )
        ],
        edinim_durumu="tam",
    )


def _huggingface_kimligi(url: str) -> tuple[str, str]:
    parcalar = _url_ayristir(url)
    bolumler = [unquote(parca) for parca in parcalar.path.split("/") if parca]
    hf_turu = "model"
    if bolumler and bolumler[0] in {"datasets", "spaces"}:
        hf_turu = "dataset" if bolumler[0] == "datasets" else "space"
        bolumler = bolumler[1:]
    if (
        not bolumler
        or len(bolumler) > 2
        or any(not _GITHUB_PARCA.fullmatch(parca) for parca in bolumler)
    ):
        raise KaynakHatasi(
            "gecersiz_huggingface_url",
            "Hugging Face URL'sinde geçerli bir model, dataset veya space kimliği yok.",
        )
    return hf_turu, "/".join(bolumler)


def _huggingface_edin(url: str, client: httpx.Client) -> KaynakBelgesi:
    hf_turu, kimlik = _huggingface_kimligi(url)
    api_aile = {"model": "models", "dataset": "datasets", "space": "spaces"}[hf_turu]
    kodlu_kimlik = quote(kimlik, safe="/")
    hf_headers = {"accept": "application/json"}
    if token := os.environ.get("HF_TOKEN", "").strip():
        hf_headers["authorization"] = f"Bearer {token}"
    api = _json_nesnesi(
        _istek(
            client,
            f"https://huggingface.co/api/{api_aile}/{kodlu_kimlik}",
            basliklar=hf_headers,
        )
    )
    if api.get("private") is True:
        raise KaynakHatasi("erisim_reddedildi", "Özel Hugging Face kaynakları edinilemez.")
    yol_oneki = "" if hf_turu == "model" else f"{api_aile}/"
    kanonik = f"https://huggingface.co/{yol_oneki}{kodlu_kimlik}"
    readme_headers = {**hf_headers, "accept": "text/markdown, text/plain;q=0.9"}
    readme_yaniti = _istek(
        client,
        f"{kanonik}/raw/main/README.md",
        basliklar=readme_headers,
        izinli_durumlar={401, 403, 404},
    )
    readme = _normalize_metin(readme_yaniti.metin()) if readme_yaniti.durum == 200 else ""
    kart = _alan_nesne(api, "cardData")
    aciklama = _alan_metin(kart, "description") or ""
    metin = "\n\n".join(parca for parca in (aciklama, readme) if parca)
    gercek_kimlik = _alan_metin(api, "id") or _alan_metin(api, "modelId") or kimlik
    sahip = _alan_metin(api, "author")
    if sahip is None and "/" in gercek_kimlik:
        sahip = gercek_kimlik.split("/", 1)[0]
    metrik_adlari = {"indirme": "downloads", "begeni": "likes"}
    metrikler = {
        ad: deger
        for ad, kaynak_ad in metrik_adlari.items()
        if (deger := _alan_sayi(api, kaynak_ad)) is not None
    }
    sinyaller = [
        KaynakSinyali(
            etiket=f"huggingface_{ad}",
            deger=deger,
            aciklama=f"Hugging Face {ad} metriği.",
            durum="bilgi",
        )
        for ad, deger in metrikler.items()
    ]
    return KaynakBelgesi(
        tur=KaynakTuru.huggingface,
        kimlik=gercek_kimlik,
        kanonik_url=kanonik,
        baslik=gercek_kimlik,
        sahip=sahip,
        yayin_tarihi=_alan_metin(api, "createdAt"),
        guncelleme_tarihi=_alan_metin(api, "lastModified"),
        dil=_alan_metin(kart, "language"),
        metin=metin,
        etiketler=_liste_metin(api.get("tags")),
        metrikler=metrikler,
        ozel={
            "huggingface_turu": hf_turu,
            "pipeline": _alan_metin(api, "pipeline_tag"),
            "kutuphane": _alan_metin(api, "library_name"),
            "gated": api.get("gated", False),
            "sha": _alan_metin(api, "sha"),
        },
        sinyaller=sinyaller,
        edinim_durumu="tam" if readme else "kismi",
    )


def _reddit_kimligi(url: str) -> str:
    parcalar = _url_ayristir(url)
    host = (parcalar.hostname or "").lower()
    bolumler = [unquote(parca) for parca in parcalar.path.split("/") if parca]
    if host == "redd.it":
        kimlik = bolumler[0] if bolumler else ""
    else:
        try:
            sira = bolumler.index("comments")
            kimlik = bolumler[sira + 1]
        except (ValueError, IndexError):
            kimlik = ""
    if not _REDDIT_KIMLIGI.fullmatch(kimlik):
        raise KaynakHatasi(
            "gecersiz_reddit_url", "Reddit URL'sinde geçerli bir gönderi kimliği yok."
        )
    return kimlik


def _zaman_iso(deger: Any) -> str | None:
    if isinstance(deger, bool) or not isinstance(deger, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(deger), tz=UTC).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _reddit_yorum_metinleri(veri: Any, ust_sinir: int = 100) -> list[str]:
    """Reddit comment tree'yi kullanıcı adlarını taşımadan sınırlı düz metne çevir."""
    try:
        kokler = veri[1]["data"]["children"]
    except (IndexError, KeyError, TypeError):
        return []
    kuyruk = list(kokler) if isinstance(kokler, list) else []
    cikti: list[str] = []
    while kuyruk and len(cikti) < ust_sinir:
        oge = kuyruk.pop(0)
        data = oge.get("data") if isinstance(oge, dict) else None
        if not isinstance(data, dict):
            continue
        govde = _alan_metin(data, "body")
        if govde and govde not in {"[removed]", "[deleted]"}:
            cikti.append(govde)
        replies = data.get("replies")
        if isinstance(replies, dict):
            alt = replies.get("data", {}).get("children", [])
            if isinstance(alt, list):
                kuyruk.extend(alt)
    return cikti


def _reddit_edin(url: str, client: httpx.Client) -> KaynakBelgesi:
    token = os.environ.get("REDDIT_ACCESS_TOKEN", "").strip()
    if not token:
        raise KaynakHatasi(
            "auth_gerekli",
            "Reddit analizi için REDDIT_ACCESS_TOKEN ortam değişkeni gereklidir.",
        )
    kimlik = _reddit_kimligi(url)
    yanit = _istek(
        client,
        f"https://oauth.reddit.com/comments/{quote(kimlik, safe='')}?raw_json=1",
        basliklar={"authorization": f"Bearer {token}", "accept": "application/json"},
    )
    veri = yanit.json()
    try:
        gonderi = veri[0]["data"]["children"][0]["data"]
    except (IndexError, KeyError, TypeError) as exc:
        raise KaynakHatasi(
            "yanit_gecersiz", "Reddit gönderi yanıtı beklenen biçimde değil."
        ) from exc
    if not isinstance(gonderi, dict):
        raise KaynakHatasi("yanit_gecersiz", "Reddit gönderi verisi nesne biçiminde değil.")
    baslik = _alan_metin(gonderi, "title") or kimlik
    selftext = _alan_metin(gonderi, "selftext") or ""
    ana_metin = selftext if selftext not in {"[removed]", "[deleted]"} else ""
    yorumlar = _reddit_yorum_metinleri(veri)
    parcalar = [ana_metin or baslik]
    if yorumlar:
        parcalar.append("\n\n".join(f"Yorum {i + 1}: {m}" for i, m in enumerate(yorumlar)))
    metin = "\n\n".join(parcalar)
    permalink = _alan_metin(gonderi, "permalink")
    kanonik = _kanonik_url_sec(
        permalink,
        f"https://www.reddit.com/comments/{quote(kimlik, safe='')}/",
    )
    metrik_adlari = {
        "puan": "score",
        "oy_orani": "upvote_ratio",
        "yorum": "num_comments",
    }
    metrikler = {
        ad: deger
        for ad, kaynak_ad in metrik_adlari.items()
        if (deger := _alan_sayi(gonderi, kaynak_ad)) is not None
    }
    subreddit = _alan_metin(gonderi, "subreddit")
    flair = _alan_metin(gonderi, "link_flair_text")
    etiketler = [deger for deger in (subreddit, flair) if deger]
    edited = gonderi.get("edited")
    return KaynakBelgesi(
        tur=KaynakTuru.reddit,
        kimlik=_alan_metin(gonderi, "id") or kimlik,
        kanonik_url=kanonik,
        baslik=baslik,
        sahip=_alan_metin(gonderi, "author"),
        yayin_tarihi=_zaman_iso(gonderi.get("created_utc")),
        guncelleme_tarihi=_zaman_iso(edited),
        dil=None,
        metin=metin,
        etiketler=etiketler,
        metrikler=metrikler,
        ozel={
            "subreddit": subreddit,
            "harici_url": _alan_metin(gonderi, "url"),
            "kendisi_metin": bool(gonderi.get("is_self", False)),
            "yetiskin": bool(gonderi.get("over_18", False)),
            "yorum_icerigi_sayisi": len(yorumlar),
        },
        sinyaller=[
            KaynakSinyali(
                etiket=f"reddit_{ad}",
                deger=deger,
                aciklama=f"Reddit {ad} metriği.",
                durum="bilgi",
            )
            for ad, deger in metrikler.items()
        ],
        edinim_durumu="tam",
    )


class _HTMLIcerikAyristirici(HTMLParser):
    _YOK_SAY = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.baslik_parcalari: list[str] = []
        self.main_parcalari: list[str] = []
        self.article_parcalari: list[str] = []
        self.body_parcalari: list[str] = []
        self.meta: dict[str, str] = {}
        self.kanonik: str | None = None
        self.dil: str | None = None
        self._yok_say_derinlik = 0
        self._main_derinlik = 0
        self._article_derinlik = 0
        self._body_derinlik = 0
        self._baslik_derinlik = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        nitelikler = {ad.lower(): (deger or "") for ad, deger in attrs}
        if tag == "html" and nitelikler.get("lang"):
            self.dil = nitelikler["lang"].split("-", 1)[0].lower()
        if tag == "meta":
            anahtar = (
                nitelikler.get("name")
                or nitelikler.get("property")
                or nitelikler.get("http-equiv")
                or ""
            ).lower()
            icerik = _normalize_metin(nitelikler.get("content"))
            if anahtar and icerik:
                self.meta[anahtar] = icerik
        if tag == "link":
            rel = {parca.lower() for parca in nitelikler.get("rel", "").split()}
            if "canonical" in rel and nitelikler.get("href"):
                self.kanonik = nitelikler["href"]
        if tag in self._YOK_SAY:
            self._yok_say_derinlik += 1
        if tag == "main":
            self._main_derinlik += 1
        if tag == "article":
            self._article_derinlik += 1
        if tag == "body":
            self._body_derinlik += 1
        if tag == "title":
            self._baslik_derinlik += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._YOK_SAY and self._yok_say_derinlik:
            self._yok_say_derinlik -= 1
        if tag == "main" and self._main_derinlik:
            self._main_derinlik -= 1
        if tag == "article" and self._article_derinlik:
            self._article_derinlik -= 1
        if tag == "body" and self._body_derinlik:
            self._body_derinlik -= 1
        if tag == "title" and self._baslik_derinlik:
            self._baslik_derinlik -= 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        metin = _normalize_metin(data)
        if not metin or self._yok_say_derinlik:
            return
        if self._baslik_derinlik:
            self.baslik_parcalari.append(metin)
        if self._main_derinlik:
            self.main_parcalari.append(metin)
        if self._article_derinlik:
            self.article_parcalari.append(metin)
        if self._body_derinlik:
            self.body_parcalari.append(metin)

    def belge_metni(self) -> str:
        parcalar = self.main_parcalari or self.article_parcalari or self.body_parcalari
        return _normalize_metin(" ".join(parcalar))


def _web_edin(url: str, client: httpx.Client) -> KaynakBelgesi:
    yanit = _istek(
        client,
        url,
        basliklar={"accept": "text/html, application/xhtml+xml;q=0.9"},
    )
    content_type = yanit.basliklar.get("content-type", "").lower()
    if (
        content_type
        and "text/html" not in content_type
        and "application/xhtml+xml" not in content_type
    ):
        raise KaynakHatasi(
            "desteklenmeyen_icerik", "Genel web adapterı yalnız HTML sayfalarını işler."
        )
    ayristirici = _HTMLIcerikAyristirici()
    try:
        ayristirici.feed(yanit.metin())
        ayristirici.close()
    except (ValueError, AssertionError) as exc:
        raise KaynakHatasi("yanit_gecersiz", "HTML sayfası ayrıştırılamadı.") from exc
    metin = ayristirici.belge_metni()
    if "\ufffd" in metin:
        raise KaynakHatasi(
            "kodlama_hatasi", "Kaynakta bozulmuş karakterler bulundu; analiz başlatılmadı."
        )
    if not metin:
        raise KaynakHatasi("icerik_bos", "HTML sayfasında analiz edilebilir metin bulunamadı.")
    kanonik = _kanonik_url_sec(ayristirici.kanonik, url)
    baslik = (
        _normalize_metin(" ".join(ayristirici.baslik_parcalari))
        or ayristirici.meta.get("og:title")
        or kanonik
    )
    anahtarlar = ayristirici.meta.get("keywords", "")
    etiketler = [temiz for oge in anahtarlar.split(",") if (temiz := _normalize_metin(oge))]
    sahip = ayristirici.meta.get("author") or ayristirici.meta.get("article:author")
    aciklama = ayristirici.meta.get("description") or ayristirici.meta.get("og:description")
    dil: str | None = None
    dil_kokeni = "unknown"
    for bildirilen, koken in (
        (ayristirici.dil, "html_lang"),
        (ayristirici.meta.get("content-language"), "html_meta"),
        (yanit.basliklar.get("content-language"), "http_header"),
        (ayristirici.meta.get("og:locale"), "og_locale"),
    ):
        if bildirilen and re.fullmatch(r"[a-zA-Z]{2,3}(?:[-_][a-zA-Z0-9]{2,8})*", bildirilen):
            dil = re.split(r"[-_]", bildirilen, maxsplit=1)[0].lower()
            dil_kokeni = koken
            break
    # Resmî Gazete Word HTML'leri lang/meta language bildirmiyor. Yalnız gerçek
    # resmî host + Türkçe mevzuat başlığı birlikteyse dili TR olarak yönlendir.
    # Yabancı dil bildirimi veya başka host için çeviri davranışı korunur.
    if (
        dil is None
        and urlsplit(url).hostname in {"www.resmigazete.gov.tr", "resmigazete.gov.tr"}
        and re.search(r"\bResm[îi]\s+Gazete\b", metin[:1000], re.I)
        and re.search(r"\bMADDE\s+\d", metin, re.I)
    ):
        dil = "tr"
        dil_kokeni = "official_rg_content"
    kodlama, kodlama_kokeni = yanit.kodlama()
    kimlik = hashlib.sha256(kanonik.encode("utf-8")).hexdigest()[:20]
    return KaynakBelgesi(
        tur=KaynakTuru.web,
        kimlik=kimlik,
        kanonik_url=kanonik,
        baslik=baslik,
        sahip=sahip,
        yayin_tarihi=ayristirici.meta.get("article:published_time"),
        guncelleme_tarihi=ayristirici.meta.get("article:modified_time"),
        dil=dil,
        metin=metin,
        etiketler=etiketler,
        metrikler={"kelime_sayisi": len(metin.split()), "karakter_sayisi": len(metin)},
        ozel={
            "aciklama": aciklama,
            "content_type": content_type or None,
            "encoding": kodlama,
            "encoding_source": kodlama_kokeni,
            "language_source": dil_kokeni,
            "source_bytes_sha256": hashlib.sha256(yanit.icerik).hexdigest(),
        },
        sinyaller=[
            KaynakSinyali(
                etiket="metin_uzunlugu",
                deger=len(metin),
                aciklama="Ayıklanan ana metnin karakter sayısı.",
                durum="bilgi",
            )
        ],
        edinim_durumu="tam",
    )


def _fixture_belgesi(url: str, tur: KaynakTuru) -> KaynakBelgesi:
    ozel: dict[str, Any] = {"fixture": True}
    etiketler = [tur.value, "fixture"]
    kimlik: str
    sahip: str | None
    baslik: str
    kanonik: str
    if tur is KaynakTuru.github:
        sahip, depo = _github_kimligi(url)
        kimlik = f"{sahip}/{depo}"
        baslik = f"{kimlik} GitHub deposu"
        kanonik = f"https://github.com/{quote(sahip)}/{quote(depo)}"
        ozel.update({"programlama_dili": "Python", "lisans": "MIT"})
    elif tur is KaynakTuru.arxiv:
        kimlik = _arxiv_kimligi(url)
        sahip = "Örnek Araştırmacı"
        baslik = "Örnek arXiv araştırması"
        kanonik = f"https://arxiv.org/abs/{quote(kimlik, safe='/')}"
        ozel.update({"yazarlar": [sahip], "doi": None})
    elif tur is KaynakTuru.reddit:
        kimlik = _reddit_kimligi(url)
        sahip = "ornek_kullanici"
        baslik = "Örnek Reddit gönderisi"
        kanonik = f"https://www.reddit.com/comments/{quote(kimlik)}/"
        ozel.update({"subreddit": "ornek"})
    elif tur is KaynakTuru.huggingface:
        hf_turu, kimlik = _huggingface_kimligi(url)
        sahip = kimlik.split("/", 1)[0] if "/" in kimlik else None
        baslik = f"{kimlik} Hugging Face kaynağı"
        api_aile = {"model": "", "dataset": "datasets/", "space": "spaces/"}[hf_turu]
        kanonik = f"https://huggingface.co/{api_aile}{quote(kimlik, safe='/')}"
        ozel.update({"huggingface_turu": hf_turu})
    else:
        parcalar = _url_ayristir(url)
        kanonik = urlunsplit((parcalar.scheme, parcalar.netloc, parcalar.path, parcalar.query, ""))
        kimlik = hashlib.sha256(kanonik.encode("utf-8")).hexdigest()[:20]
        sahip = parcalar.hostname
        baslik = "Örnek web sayfası"
    return KaynakBelgesi(
        tur=tur,
        kimlik=kimlik,
        kanonik_url=kanonik,
        baslik=baslik,
        sahip=sahip,
        yayin_tarihi="2026-01-01T00:00:00Z",
        guncelleme_tarihi="2026-01-02T00:00:00Z",
        dil="tr",
        metin=f"{baslik} için ağsız ve deterministik analiz içeriği.",
        etiketler=etiketler,
        metrikler={"fixture_degeri": 1},
        ozel=ozel,
        sinyaller=[
            KaynakSinyali(
                etiket="fixture",
                deger=True,
                aciklama="Ağsız ve deterministik kaynak belgesi.",
                durum="bilgi",
            )
        ],
        edinim_durumu="fixture",
    )


def kaynak_edin(url: str, client: httpx.Client | None = None) -> KaynakBelgesi:
    """Kaynağı edinip ortak belge modeline dönüştürür.

    Verilen istemcinin yaşam döngüsü çağırana aittir. İstemci verilmezse proxy ortam
    değişkenlerinden etkilenmeyen, yönlendirmeleri kapalı kısa ömürlü istemci kullanılır.
    """

    tur = kaynak_turu_bul(url)
    if tur is KaynakTuru.youtube:
        raise KaynakHatasi(
            "youtube_legacy",
            "YouTube analizi mevcut ytcore pipeline'ı üzerinden çalıştırılmalıdır.",
        )
    if os.environ.get("RASATHANE_SOURCE_FIXTURE", "").strip() == "1":
        return _fixture_belgesi(url, tur)

    istemci_bizim = client is None
    http = client or httpx.Client(
        timeout=_ISTEK_ZAMAN_ASIMI_SN,
        follow_redirects=False,
        trust_env=False,
    )
    try:
        if tur is KaynakTuru.github:
            return _github_edin(url, http)
        if tur is KaynakTuru.arxiv:
            return _arxiv_edin(url, http)
        if tur is KaynakTuru.reddit:
            return _reddit_edin(url, http)
        if tur is KaynakTuru.huggingface:
            return _huggingface_edin(url, http)
        return _web_edin(url, http)
    finally:
        if istemci_bizim:
            http.close()


__all__ = [
    "KaynakBelgesi",
    "KaynakHatasi",
    "KaynakSinyali",
    "KaynakTuru",
    "kaynak_edin",
    "kaynak_turu_bul",
]
