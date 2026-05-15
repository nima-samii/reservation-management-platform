"""
Seed script: populate countries and default channels.
Run once after the initial migration:
    python scripts/seed_countries.py

Channel env vars (optional — placeholders used if not set):
  CHANNEL_1_NAME, CHANNEL_1_ID, CHANNEL_1_INVITE
  CHANNEL_2_NAME, CHANNEL_2_ID, CHANNEL_2_INVITE
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.db.models.channel import Channel
from app.db.models.country import Country
from app.db.session import AsyncSessionFactory


COUNTRIES: list[dict] = [
    {"code": "AF", "name": "Afghanistan", "flag_emoji": "🇦🇫"},
    {"code": "AL", "name": "Albania", "flag_emoji": "🇦🇱"},
    {"code": "DZ", "name": "Algeria", "flag_emoji": "🇩🇿"},
    {"code": "AD", "name": "Andorra", "flag_emoji": "🇦🇩"},
    {"code": "AO", "name": "Angola", "flag_emoji": "🇦🇴"},
    {"code": "AG", "name": "Antigua and Barbuda", "flag_emoji": "🇦🇬"},
    {"code": "AR", "name": "Argentina", "flag_emoji": "🇦🇷"},
    {"code": "AM", "name": "Armenia", "flag_emoji": "🇦🇲"},
    {"code": "AU", "name": "Australia", "flag_emoji": "🇦🇺"},
    {"code": "AT", "name": "Austria", "flag_emoji": "🇦🇹"},
    {"code": "AZ", "name": "Azerbaijan", "flag_emoji": "🇦🇿"},
    {"code": "BS", "name": "Bahamas", "flag_emoji": "🇧🇸"},
    {"code": "BH", "name": "Bahrain", "flag_emoji": "🇧🇭"},
    {"code": "BD", "name": "Bangladesh", "flag_emoji": "🇧🇩"},
    {"code": "BB", "name": "Barbados", "flag_emoji": "🇧🇧"},
    {"code": "BY", "name": "Belarus", "flag_emoji": "🇧🇾"},
    {"code": "BE", "name": "Belgium", "flag_emoji": "🇧🇪"},
    {"code": "BZ", "name": "Belize", "flag_emoji": "🇧🇿"},
    {"code": "BJ", "name": "Benin", "flag_emoji": "🇧🇯"},
    {"code": "BT", "name": "Bhutan", "flag_emoji": "🇧🇹"},
    {"code": "BO", "name": "Bolivia", "flag_emoji": "🇧🇴"},
    {"code": "BA", "name": "Bosnia and Herzegovina", "flag_emoji": "🇧🇦"},
    {"code": "BW", "name": "Botswana", "flag_emoji": "🇧🇼"},
    {"code": "BR", "name": "Brazil", "flag_emoji": "🇧🇷"},
    {"code": "BN", "name": "Brunei", "flag_emoji": "🇧🇳"},
    {"code": "BG", "name": "Bulgaria", "flag_emoji": "🇧🇬"},
    {"code": "BF", "name": "Burkina Faso", "flag_emoji": "🇧🇫"},
    {"code": "BI", "name": "Burundi", "flag_emoji": "🇧🇮"},
    {"code": "CV", "name": "Cabo Verde", "flag_emoji": "🇨🇻"},
    {"code": "KH", "name": "Cambodia", "flag_emoji": "🇰🇭"},
    {"code": "CM", "name": "Cameroon", "flag_emoji": "🇨🇲"},
    {"code": "CA", "name": "Canada", "flag_emoji": "🇨🇦"},
    {"code": "CF", "name": "Central African Republic", "flag_emoji": "🇨🇫"},
    {"code": "TD", "name": "Chad", "flag_emoji": "🇹🇩"},
    {"code": "CL", "name": "Chile", "flag_emoji": "🇨🇱"},
    {"code": "CN", "name": "China", "flag_emoji": "🇨🇳"},
    {"code": "CO", "name": "Colombia", "flag_emoji": "🇨🇴"},
    {"code": "KM", "name": "Comoros", "flag_emoji": "🇰🇲"},
    {"code": "CG", "name": "Congo", "flag_emoji": "🇨🇬"},
    {"code": "CR", "name": "Costa Rica", "flag_emoji": "🇨🇷"},
    {"code": "HR", "name": "Croatia", "flag_emoji": "🇭🇷"},
    {"code": "CU", "name": "Cuba", "flag_emoji": "🇨🇺"},
    {"code": "CY", "name": "Cyprus", "flag_emoji": "🇨🇾"},
    {"code": "CZ", "name": "Czech Republic", "flag_emoji": "🇨🇿"},
    {"code": "DK", "name": "Denmark", "flag_emoji": "🇩🇰"},
    {"code": "DJ", "name": "Djibouti", "flag_emoji": "🇩🇯"},
    {"code": "DO", "name": "Dominican Republic", "flag_emoji": "🇩🇴"},
    {"code": "EC", "name": "Ecuador", "flag_emoji": "🇪🇨"},
    {"code": "EG", "name": "Egypt", "flag_emoji": "🇪🇬"},
    {"code": "SV", "name": "El Salvador", "flag_emoji": "🇸🇻"},
    {"code": "GQ", "name": "Equatorial Guinea", "flag_emoji": "🇬🇶"},
    {"code": "ER", "name": "Eritrea", "flag_emoji": "🇪🇷"},
    {"code": "EE", "name": "Estonia", "flag_emoji": "🇪🇪"},
    {"code": "SZ", "name": "Eswatini", "flag_emoji": "🇸🇿"},
    {"code": "ET", "name": "Ethiopia", "flag_emoji": "🇪🇹"},
    {"code": "FJ", "name": "Fiji", "flag_emoji": "🇫🇯"},
    {"code": "FI", "name": "Finland", "flag_emoji": "🇫🇮"},
    {"code": "FR", "name": "France", "flag_emoji": "🇫🇷"},
    {"code": "GA", "name": "Gabon", "flag_emoji": "🇬🇦"},
    {"code": "GM", "name": "Gambia", "flag_emoji": "🇬🇲"},
    {"code": "GE", "name": "Georgia", "flag_emoji": "🇬🇪"},
    {"code": "DE", "name": "Germany", "flag_emoji": "🇩🇪"},
    {"code": "GH", "name": "Ghana", "flag_emoji": "🇬🇭"},
    {"code": "GR", "name": "Greece", "flag_emoji": "🇬🇷"},
    {"code": "GD", "name": "Grenada", "flag_emoji": "🇬🇩"},
    {"code": "GT", "name": "Guatemala", "flag_emoji": "🇬🇹"},
    {"code": "GN", "name": "Guinea", "flag_emoji": "🇬🇳"},
    {"code": "GW", "name": "Guinea-Bissau", "flag_emoji": "🇬🇼"},
    {"code": "GY", "name": "Guyana", "flag_emoji": "🇬🇾"},
    {"code": "HT", "name": "Haiti", "flag_emoji": "🇭🇹"},
    {"code": "HN", "name": "Honduras", "flag_emoji": "🇭🇳"},
    {"code": "HU", "name": "Hungary", "flag_emoji": "🇭🇺"},
    {"code": "IS", "name": "Iceland", "flag_emoji": "🇮🇸"},
    {"code": "IN", "name": "India", "flag_emoji": "🇮🇳"},
    {"code": "ID", "name": "Indonesia", "flag_emoji": "🇮🇩"},
    {"code": "IR", "name": "Iran", "flag_emoji": "🇮🇷"},
    {"code": "IQ", "name": "Iraq", "flag_emoji": "🇮🇶"},
    {"code": "IE", "name": "Ireland", "flag_emoji": "🇮🇪"},
    {"code": "IL", "name": "Israel", "flag_emoji": "🇮🇱"},
    {"code": "IT", "name": "Italy", "flag_emoji": "🇮🇹"},
    {"code": "JM", "name": "Jamaica", "flag_emoji": "🇯🇲"},
    {"code": "JP", "name": "Japan", "flag_emoji": "🇯🇵"},
    {"code": "JO", "name": "Jordan", "flag_emoji": "🇯🇴"},
    {"code": "KZ", "name": "Kazakhstan", "flag_emoji": "🇰🇿"},
    {"code": "KE", "name": "Kenya", "flag_emoji": "🇰🇪"},
    {"code": "KI", "name": "Kiribati", "flag_emoji": "🇰🇮"},
    {"code": "KW", "name": "Kuwait", "flag_emoji": "🇰🇼"},
    {"code": "KG", "name": "Kyrgyzstan", "flag_emoji": "🇰🇬"},
    {"code": "LA", "name": "Laos", "flag_emoji": "🇱🇦"},
    {"code": "LV", "name": "Latvia", "flag_emoji": "🇱🇻"},
    {"code": "LB", "name": "Lebanon", "flag_emoji": "🇱🇧"},
    {"code": "LS", "name": "Lesotho", "flag_emoji": "🇱🇸"},
    {"code": "LR", "name": "Liberia", "flag_emoji": "🇱🇷"},
    {"code": "LY", "name": "Libya", "flag_emoji": "🇱🇾"},
    {"code": "LI", "name": "Liechtenstein", "flag_emoji": "🇱🇮"},
    {"code": "LT", "name": "Lithuania", "flag_emoji": "🇱🇹"},
    {"code": "LU", "name": "Luxembourg", "flag_emoji": "🇱🇺"},
    {"code": "MG", "name": "Madagascar", "flag_emoji": "🇲🇬"},
    {"code": "MW", "name": "Malawi", "flag_emoji": "🇲🇼"},
    {"code": "MY", "name": "Malaysia", "flag_emoji": "🇲🇾"},
    {"code": "MV", "name": "Maldives", "flag_emoji": "🇲🇻"},
    {"code": "ML", "name": "Mali", "flag_emoji": "🇲🇱"},
    {"code": "MT", "name": "Malta", "flag_emoji": "🇲🇹"},
    {"code": "MH", "name": "Marshall Islands", "flag_emoji": "🇲🇭"},
    {"code": "MR", "name": "Mauritania", "flag_emoji": "🇲🇷"},
    {"code": "MU", "name": "Mauritius", "flag_emoji": "🇲🇺"},
    {"code": "MX", "name": "Mexico", "flag_emoji": "🇲🇽"},
    {"code": "FM", "name": "Micronesia", "flag_emoji": "🇫🇲"},
    {"code": "MD", "name": "Moldova", "flag_emoji": "🇲🇩"},
    {"code": "MC", "name": "Monaco", "flag_emoji": "🇲🇨"},
    {"code": "MN", "name": "Mongolia", "flag_emoji": "🇲🇳"},
    {"code": "ME", "name": "Montenegro", "flag_emoji": "🇲🇪"},
    {"code": "MA", "name": "Morocco", "flag_emoji": "🇲🇦"},
    {"code": "MZ", "name": "Mozambique", "flag_emoji": "🇲🇿"},
    {"code": "MM", "name": "Myanmar", "flag_emoji": "🇲🇲"},
    {"code": "NA", "name": "Namibia", "flag_emoji": "🇳🇦"},
    {"code": "NR", "name": "Nauru", "flag_emoji": "🇳🇷"},
    {"code": "NP", "name": "Nepal", "flag_emoji": "🇳🇵"},
    {"code": "NL", "name": "Netherlands", "flag_emoji": "🇳🇱"},
    {"code": "NZ", "name": "New Zealand", "flag_emoji": "🇳🇿"},
    {"code": "NI", "name": "Nicaragua", "flag_emoji": "🇳🇮"},
    {"code": "NE", "name": "Niger", "flag_emoji": "🇳🇪"},
    {"code": "NG", "name": "Nigeria", "flag_emoji": "🇳🇬"},
    {"code": "NO", "name": "Norway", "flag_emoji": "🇳🇴"},
    {"code": "OM", "name": "Oman", "flag_emoji": "🇴🇲"},
    {"code": "PK", "name": "Pakistan", "flag_emoji": "🇵🇰"},
    {"code": "PW", "name": "Palau", "flag_emoji": "🇵🇼"},
    {"code": "PA", "name": "Panama", "flag_emoji": "🇵🇦"},
    {"code": "PG", "name": "Papua New Guinea", "flag_emoji": "🇵🇬"},
    {"code": "PY", "name": "Paraguay", "flag_emoji": "🇵🇾"},
    {"code": "PE", "name": "Peru", "flag_emoji": "🇵🇪"},
    {"code": "PH", "name": "Philippines", "flag_emoji": "🇵🇭"},
    {"code": "PL", "name": "Poland", "flag_emoji": "🇵🇱"},
    {"code": "PT", "name": "Portugal", "flag_emoji": "🇵🇹"},
    {"code": "QA", "name": "Qatar", "flag_emoji": "🇶🇦"},
    {"code": "RO", "name": "Romania", "flag_emoji": "🇷🇴"},
    {"code": "RU", "name": "Russia", "flag_emoji": "🇷🇺"},
    {"code": "RW", "name": "Rwanda", "flag_emoji": "🇷🇼"},
    {"code": "KN", "name": "Saint Kitts and Nevis", "flag_emoji": "🇰🇳"},
    {"code": "LC", "name": "Saint Lucia", "flag_emoji": "🇱🇨"},
    {"code": "VC", "name": "Saint Vincent and the Grenadines", "flag_emoji": "🇻🇨"},
    {"code": "WS", "name": "Samoa", "flag_emoji": "🇼🇸"},
    {"code": "SM", "name": "San Marino", "flag_emoji": "🇸🇲"},
    {"code": "ST", "name": "Sao Tome and Principe", "flag_emoji": "🇸🇹"},
    {"code": "SA", "name": "Saudi Arabia", "flag_emoji": "🇸🇦"},
    {"code": "SN", "name": "Senegal", "flag_emoji": "🇸🇳"},
    {"code": "RS", "name": "Serbia", "flag_emoji": "🇷🇸"},
    {"code": "SC", "name": "Seychelles", "flag_emoji": "🇸🇨"},
    {"code": "SL", "name": "Sierra Leone", "flag_emoji": "🇸🇱"},
    {"code": "SG", "name": "Singapore", "flag_emoji": "🇸🇬"},
    {"code": "SK", "name": "Slovakia", "flag_emoji": "🇸🇰"},
    {"code": "SI", "name": "Slovenia", "flag_emoji": "🇸🇮"},
    {"code": "SB", "name": "Solomon Islands", "flag_emoji": "🇸🇧"},
    {"code": "SO", "name": "Somalia", "flag_emoji": "🇸🇴"},
    {"code": "ZA", "name": "South Africa", "flag_emoji": "🇿🇦"},
    {"code": "SS", "name": "South Sudan", "flag_emoji": "🇸🇸"},
    {"code": "ES", "name": "Spain", "flag_emoji": "🇪🇸"},
    {"code": "LK", "name": "Sri Lanka", "flag_emoji": "🇱🇰"},
    {"code": "SD", "name": "Sudan", "flag_emoji": "🇸🇩"},
    {"code": "SR", "name": "Suriname", "flag_emoji": "🇸🇷"},
    {"code": "SE", "name": "Sweden", "flag_emoji": "🇸🇪"},
    {"code": "CH", "name": "Switzerland", "flag_emoji": "🇨🇭"},
    {"code": "SY", "name": "Syria", "flag_emoji": "🇸🇾"},
    {"code": "TW", "name": "Taiwan", "flag_emoji": "🇹🇼"},
    {"code": "TJ", "name": "Tajikistan", "flag_emoji": "🇹🇯"},
    {"code": "TZ", "name": "Tanzania", "flag_emoji": "🇹🇿"},
    {"code": "TH", "name": "Thailand", "flag_emoji": "🇹🇭"},
    {"code": "TL", "name": "Timor-Leste", "flag_emoji": "🇹🇱"},
    {"code": "TG", "name": "Togo", "flag_emoji": "🇹🇬"},
    {"code": "TO", "name": "Tonga", "flag_emoji": "🇹🇴"},
    {"code": "TT", "name": "Trinidad and Tobago", "flag_emoji": "🇹🇹"},
    {"code": "TN", "name": "Tunisia", "flag_emoji": "🇹🇳"},
    {"code": "TR", "name": "Turkey", "flag_emoji": "🇹🇷"},
    {"code": "TM", "name": "Turkmenistan", "flag_emoji": "🇹🇲"},
    {"code": "TV", "name": "Tuvalu", "flag_emoji": "🇹🇻"},
    {"code": "UG", "name": "Uganda", "flag_emoji": "🇺🇬"},
    {"code": "UA", "name": "Ukraine", "flag_emoji": "🇺🇦"},
    {"code": "AE", "name": "United Arab Emirates", "flag_emoji": "🇦🇪"},
    {"code": "GB", "name": "United Kingdom", "flag_emoji": "🇬🇧"},
    {"code": "US", "name": "United States", "flag_emoji": "🇺🇸"},
    {"code": "UY", "name": "Uruguay", "flag_emoji": "🇺🇾"},
    {"code": "UZ", "name": "Uzbekistan", "flag_emoji": "🇺🇿"},
    {"code": "VU", "name": "Vanuatu", "flag_emoji": "🇻🇺"},
    {"code": "VE", "name": "Venezuela", "flag_emoji": "🇻🇪"},
    {"code": "VN", "name": "Vietnam", "flag_emoji": "🇻🇳"},
    {"code": "YE", "name": "Yemen", "flag_emoji": "🇾🇪"},
    {"code": "ZM", "name": "Zambia", "flag_emoji": "🇿🇲"},
    {"code": "ZW", "name": "Zimbabwe", "flag_emoji": "🇿🇼"},
]


def _build_channel_defaults() -> list[dict]:
    channels = []
    for i in range(1, 4):
        ch_id_env = os.environ.get(f"CHANNEL_{i}_ID")
        if i == 1 and not ch_id_env:
            # Always seed at least one placeholder channel so slot generation works
            ch_id_env = "-1001000000001"
        if not ch_id_env:
            continue
        channels.append({
            "name": os.environ.get(f"CHANNEL_{i}_NAME", f"Channel {i}"),
            "telegram_channel_id": int(ch_id_env),
            "invite_link": os.environ.get(f"CHANNEL_{i}_INVITE") or None,
            "priority": i - 1,
            "is_active": True,
        })
    return channels


async def seed() -> None:
    import uuid
    async with AsyncSessionFactory() as session:
        # ── Countries ──────────────────────────────────────────────────────
        for entry in COUNTRIES:
            existing = await session.execute(
                select(Country).where(Country.code == entry["code"])
            )
            if existing.scalars().first():
                continue
            session.add(Country(
                id=uuid.uuid4(),
                code=entry["code"],
                name=entry["name"],
                flag_emoji=entry.get("flag_emoji"),
                is_active=True,
            ))

        await session.commit()
        print(f"✅ Seeded {len(COUNTRIES)} countries.")

        # ── Channels ───────────────────────────────────────────────────────
        channel_defs = _build_channel_defaults()
        seeded_channels = 0
        for ch in channel_defs:
            existing = await session.execute(
                select(Channel).where(
                    Channel.telegram_channel_id == ch["telegram_channel_id"]
                )
            )
            if existing.scalars().first():
                continue
            session.add(Channel(
                id=uuid.uuid4(),
                name=ch["name"],
                telegram_channel_id=ch["telegram_channel_id"],
                invite_link=ch["invite_link"],
                capacity=100,
                priority=ch["priority"],
                is_active=ch["is_active"],
            ))
            seeded_channels += 1

        await session.commit()
        print(f"✅ Seeded {seeded_channels} channel(s).")


if __name__ == "__main__":
    asyncio.run(seed())
