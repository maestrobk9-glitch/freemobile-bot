# ============================================================
# VIP DETECTOR (STRICT)
# ============================================================

def evaluate_vip_expanded(num):
    """
    STRICT VIP FILTER

    ULTRA VIP:
      AAAAAAAA
      ABABABAB
      ABCDABCD
      ABBAABBA
      Palindrome قوي

    SUPER VIP:
      AAAABBBB
      AABBCCDD
      AAAAxxxx
      xxxxAAAA

    VIP:
      AAAAAxxx
      xxxAAAAA
      AABBAABB

    أي رقم لا يطابق نمطاً واضحاً => None
    """

    clean = (
        str(num)
        .replace(" ", "")
        .replace("-", "")
        .strip()
    )

    # يجب أن يكون رقم Free Mobile فرنسي
    if len(clean) != 10:
        return None

    if not (clean.startswith("06") or clean.startswith("07")):
        return None

    # الجزء المهم بعد 06 / 07
    d = clean[2:]

    if len(d) != 8:
        return None

    # ======================================================
    # 💎 ULTRA VIP
    # ======================================================

    # AAAAAAAA
    if len(set(d)) == 1:
        return "💎 ULTRA VIP — AAAAAAAA"

    # ABABABAB
    if (
        d[0] == d[2] == d[4] == d[6]
        and
        d[1] == d[3] == d[5] == d[7]
        and
        d[0] != d[1]
    ):
        return "💎 ULTRA VIP — ABABABAB"

    # ABCDABCD
    if d[:4] == d[4:]:
        return "💎 ULTRA VIP — ABCDABCD"

    # ABBAABBA
    if (
        d[:4] == d[4:]
        and
        d[0] == d[3]
        and
        d[1] == d[2]
        and
        d[0] != d[1]
    ):
        return "💎 ULTRA VIP — ABBAABBA"

    # Palindrome كامل
    if d == d[::-1]:
        return "💎 ULTRA VIP — PALINDROME"

    # ======================================================
    # 🔥 SUPER VIP
    # ======================================================

    # AAAABBBB
    if (
        d[0] == d[1] == d[2] == d[3]
        and
        d[4] == d[5] == d[6] == d[7]
        and
        d[0] != d[4]
    ):
        return "🔥 SUPER VIP — AAAABBBB"

    # AABBCCDD
    if (
        d[0] == d[1]
        and d[2] == d[3]
        and d[4] == d[5]
        and d[6] == d[7]
        and len({
            d[0], d[2], d[4], d[6]
        }) >= 3
    ):
        return "🔥 SUPER VIP — AABBCCDD"

    # AAAAxxxx
    if (
        d[0] == d[1] == d[2] == d[3]
        and
        len(set(d[4:])) > 1
    ):
        return "🔥 SUPER VIP — AAAAxxxx"

    # xxxxAAAA
    if (
        d[4] == d[5] == d[6] == d[7]
        and
        len(set(d[:4])) > 1
    ):
        return "🔥 SUPER VIP — xxxxAAAA"

    # ======================================================
    # ⭐ VIP
    # ======================================================

    # AAAAAxxx
    if (
        d[0] == d[1] == d[2] == d[3] == d[4]
        and
        len(set(d[5:])) > 1
    ):
        return "⭐ VIP — AAAAAxxx"

    # xxxAAAAA
    if (
        d[3] == d[4] == d[5] == d[6] == d[7]
        and
        len(set(d[:3])) > 1
    ):
        return "⭐ VIP — xxxAAAAA"

    # AABB AABB
    if (
        d[0] == d[1]
        and
        d[2] == d[3]
        and
        d[4] == d[5]
        and
        d[6] == d[7]
        and
        d[0] != d[2]
        and
        d[2] != d[4]
        and
        d[4] != d[6]
    ):
        return "⭐ VIP — AABBAABB"

    # ======================================================
    # ❌ أي شيء آخر = ليس VIP
    # ======================================================

    return None
