#!/usr/bin/env python3
"""coords_test.py - unit cases for the shared map-link / coordinate parser (helpers/coords.py).
Pure, offline, no deps. Proves every LINK_LL shape parses, PLAIN_LL accepts a real pair, the
false-positive guards hold (area magnitude / low-precision ratio / out-of-bounds / near-zero), and a
short link ships as mapLink with no coord."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "helpers"))
import coords as CO  # noqa: E402


def check(name, cond):
    if not cond:
        raise AssertionError(name)


# each LINK_LL shape -> coords
check("q=", CO.coords_from_url("https://maps.google.com/?q=40.4168,-3.7038") == (40.4168, -3.7038))
check("@", CO.coords_from_url("https://www.google.com/maps/@41.3851,2.1734,15z") == (41.3851, 2.1734))
check("!3d", CO.coords_from_url("https://google.com/maps/x/data=!3d51.5074!4d-0.1278") == (51.5074, -0.1278))
check("place", CO.coords_from_url("https://google.com/maps/place/48.8566,2.3522") == (48.8566, 2.3522))
check("geo", CO.coords_from_url("geo:52.520,13.405") == (52.52, 13.405))
# saddr/sll (origin/viewport) are NOT accepted
check("no-saddr", CO.coords_from_url("https://maps.google.com/?saddr=40.001,-3.001") is None)
# text: URL with coords -> both; short link -> mapLink only
c, ml = CO.coords_and_link_from_text("see https://maps.google.com/?q=40.4168,-3.7038 near site")
check("text-url-coords", c == (40.4168, -3.7038) and ml is not None and "maps.google.com" in ml)
c, ml = CO.coords_and_link_from_text("loc: https://maps.app.goo.gl/abc123")
check("shortlink", c is None and ml == "https://maps.app.goo.gl/abc123")
# plain pair
c, ml = CO.coords_and_link_from_text("Coordinates 45.4642, 9.1900")
check("plain", c == (45.4642, 9.19) and ml is None)
# FALSE-POSITIVE guards
check("area", CO.coords_and_link_from_text("Size 51,500 sq m")[0] is None)
check("ratio", CO.coords_and_link_from_text("ratio 1.2, 3.4")[0] is None)  # <3 decimals
check("oob", CO.coords_and_link_from_text("199.1234, 8.5678")[0] is None)  # lat>90
check("nearzero", CO.coords_and_link_from_text("0.000, 0.000")[0] is None)
# PERIOD-as-thousands guard (ES/DE size lists) + the coordinate-cue requirement for a bare pair:
# an unlabelled '12.500, 18.500' (= 12,500 and 18,500 sqm) must NOT be misread as lat 12.5 / lng 18.5
check("thousands-nocue", CO.coords_and_link_from_text("Superficie 12.500, 18.500 m2")[0] is None)
check("cue-too-far", CO.coords_and_link_from_text(
    "GPS satellite navigation available; the warehouse is 12.500, 18.500 m2 in size")[0] is None)
# a cue immediately before the pair (any of several languages) IS trusted
check("cued-es", CO.coords_and_link_from_text("Coordenadas: 40.4168, -3.7038")[0] == (40.4168, -3.7038))
check("cued-gps", CO.coords_and_link_from_text("GPS 45.4642, 9.1900")[0] == (45.4642, 9.19))
# the cue must be a real LABEL, not a substring buried in a common word: 'plataforma' embeds 'lat',
# 'lateral' embeds 'lat', 'colonia' embeds 'lon' - none may admit a size pair as a pin (ES/DE)
check("plataforma", CO.coords_and_link_from_text("Plataforma de 12.500, 25.000 m2")[0] is None)
check("lateral", CO.coords_and_link_from_text("Acceso lateral 12.500, 18.500 m2")[0] is None)
check("colonia", CO.coords_and_link_from_text("Colonia industrial 12.500, 25.000")[0] is None)
# long-form labels still resolve (leading-anchored prefixes)
check("latitud", CO.coords_and_link_from_text("Latitud/Longitud 41.3851, 2.1734")[0] == (41.3851, 2.1734))

print("COORDS TEST: PASS")
