"""Carrier export. One clean CSV the merchant uploads to the carrier's bulk-import page.

Each carrier's bulk template differs and changes over time, so the export uses explicit column
names that map one-to-one to what every Algerian carrier asks for (reference, name, phone,
wilaya code + name, commune, address, product, COD amount, stop desk). API adapters can be
added per carrier with the merchant's own keys.
"""

import csv
import io

from .algeria import WILAYA_BY_CODE

CARRIERS = {
    "yalidine": "Yalidine",
    "zr": "ZR Express",
    "maystro": "Maystro Delivery",
    "noest": "NOEST",
    "ecotrack": "Ecotrack",
    "other": "Autre / أخرى",
}

COLUMNS = [
    "reference", "nom_client", "telephone", "code_wilaya", "wilaya", "commune", "adresse",
    "produit", "quantite", "montant_cod", "stop_desk", "remarque",
]


def export_csv(orders) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    for order in orders:
        fr_name = WILAYA_BY_CODE.get(order.wilaya_code, ("", ""))[0]
        qty = sum(int(i.get("qty", 1)) for i in order.items or []) or 1
        remark = order.note or ""
        if order.preferred_slot:
            remark = (remark + " | " if remark else "") + ("Livrer le matin" if order.preferred_slot == "morning" else "Livrer l'après-midi")
        writer.writerow([
            order.external_id or order.id[:8].upper(),
            order.customer_name,
            order.phone,
            order.wilaya_code or "",
            fr_name,
            order.commune,
            order.address,
            order.items_label.replace("، ", " + "),
            qty,
            order.total_dzd,
            1 if order.delivery_type == "stopdesk" else 0,
            remark,
        ])
    return ("﻿" + buffer.getvalue()).encode("utf-8")  # BOM so Excel shows Arabic correctly
