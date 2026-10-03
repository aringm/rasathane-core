/** Kaynağın olay tarihi ile kayıt/edinim zamanını birbirine dönüştürmez. */
export function recordDate(item, sourceType) {
  const provenance = item.provenance || {};
  if (provenance.decision_date) {
    return {
      label: "Karar tarihi: ",
      value: provenance.decision_date,
      dayOnly: true,
    };
  }
  if (item.published_at) {
    return {
      label:
        provenance.date_kind === "publication" || sourceType === "resmi_gazete"
          ? "Yayım tarihi: "
          : "Kaynak tarih kaydı: ",
      value: item.published_at,
      dayOnly: true,
    };
  }
  return {
    label: item.source_id ? "Edinim zamanı: " : "Kayıt tarihi: ",
    value: provenance.source_fetched_at || item.created_at,
    dayOnly: false,
  };
}
