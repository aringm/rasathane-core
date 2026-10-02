from __future__ import annotations

# Faz 1 dersi: GERÇEK kod hatası (parse/tip/import/key) model/ağ ham hatadan ayrılır.
# Bunlar re-raise edilir (görünür crash — maskeleme YOK); yalnız güvenilmez-veri sınırından
# (model çıktısı, dış API/ağ) gelen diğer Exception'lar sınırda graceful guard'lanır.
# Tek kaynak (content/node, content/dokum, transcript/node ortak kullanır).
KOD_HATALARI = (NameError, AttributeError, TypeError, ImportError, KeyError, IndexError)
