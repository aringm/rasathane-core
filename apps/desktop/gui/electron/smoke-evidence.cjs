"use strict";

// QA kabulü: boş arama bir hata değildir; bulunmayan kanıt kesinlik üretemez.
function conservativeSearchClaims(claims) {
  return Array.isArray(claims) && claims.length > 0 && claims.every((claim) => {
    if (!claim || claim.karar !== "BELİRSİZ" || claim.guven !== 0 ||
        claim.bagimsiz_dogrulama !== false) return false;
    if (claim.kanit_turu === "arama_ozeti") {
      return Array.isArray(claim.kaynaklar) && claim.kaynaklar.length > 0;
    }
    return claim.kanit_turu === "yok" &&
      Array.isArray(claim.kaynaklar) && claim.kaynaklar.length === 0 &&
      Array.isArray(claim.ilgili_kaynaklar) && claim.ilgili_kaynaklar.length === 0 &&
      claim.aday_karar === null && typeof claim.gerekce === "string" &&
      claim.gerekce.trim().length > 0;
  });
}
module.exports = { conservativeSearchClaims };
