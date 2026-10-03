// Kaynak biçimi transport türünden ayrıdır: PDF, web adapter'ıyla edinilir.
export function sourceFormatDetails(result, index = result.index || {}) {
  const source = { ...(index.kaynak_ozel || {}), ...(result.quality_provenance?.source || {}) };
  if (source.source_format !== "pdf" && source.format !== "pdf") return null;
  const integer = value => Number.isInteger(value) && value >= 0 ? value : null;
  const pages = integer(source.page_count), textPages = integer(source.text_page_count);
  const reasons = Array.isArray(source.truncation_reasons) ? source.truncation_reasons.filter(item => typeof item === "string").slice(0, 12) : [];
  const reasonLabels = {
    pages_without_text: "Bazı sayfalarda metin katmanı bulunamadı.",
    page_limit: "Sayfa sınırı nedeniyle belgenin bir bölümü okunamadı.",
    character_limit: "Metin uzunluğu sınırı nedeniyle içerik kısaltıldı.",
    time_limit: "Çözümleme süresi dolduğu için kalan içerik okunamadı.",
    stream_budget: "PDF içerik boyutu çözümleme sınırını aştı.",
    parser_warnings: "PDF okuyucu yapısal uyarılar bildirdi; çıkarılan metni kaynakla kontrol edin.",
    char_limit: "Metin uzunluğu sınırı nedeniyle içerik kısaltıldı.",
    page_stream_limit: "Büyük sayfa içeriği kaynak sınırı nedeniyle atlandı.",
    total_stream_limit: "Toplam çözümleme sınırı nedeniyle içerik kısaltıldı.",
  };
  const partial = source.full_text_extracted === false || reasons.length > 0 || pages != null && textPages != null && textPages < pages;
  const scope = pages != null && textPages != null
    ? `${textPages}/${pages} sayfada metin alındı.`
    : pages != null ? `${pages} sayfalık PDF’nin metin katmanı okundu.` : "PDF’nin metin katmanı okundu.";
  const notices = [
    partial ? "Kısmi PDF metni." : "PDF metin katmanı.", scope,
    source.ocr_performed === true ? "OCR uygulanmış; sonuçları kaynakla kontrol edin." : "OCR yapılmadı. Görseller, tablo düzeni ve taranmış içerik değerlendirilmedi.",
    ...reasons.map(reason => reasonLabels[reason] || "PDF çözümleme sınırı nedeniyle içerik kısmen alındı."),
  ];
  return {
    format: "pdf", label: "PDF (Web)", pages, textPages, partial,
    description: notices.join(" "),
    bytesSha256: source.bytes_sha256 || source.source_bytes_sha256 || null,
    extractionMethod: source.extraction_method || null,
  };
}
