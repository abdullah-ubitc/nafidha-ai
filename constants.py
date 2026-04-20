"""Shared constants: tariff rates, exchange rates, document types, timelines"""

CURRENT_CBL_RATES = {
    "USD": 4.87, "EUR": 5.28, "GBP": 6.15, "AED": 1.33,
    "SAR": 1.30, "TRY": 0.16, "CHF": 5.45, "JPY": 0.033, "CNY": 0.67
}

TARIFF_2022 = {
    "01": {"rate": 0.05, "desc_ar": "حيوانات حية", "desc_en": "Live animals"},
    "02": {"rate": 0.10, "desc_ar": "لحوم", "desc_en": "Meat and edible offal"},
    "03": {"rate": 0.10, "desc_ar": "أسماك", "desc_en": "Fish and crustaceans"},
    "04": {"rate": 0.05, "desc_ar": "منتجات ألبان", "desc_en": "Dairy produce"},
    "05": {"rate": 0.05, "desc_ar": "منتجات حيوانية أخرى", "desc_en": "Other animal products"},
    "06": {"rate": 0.10, "desc_ar": "أشجار ونباتات حية", "desc_en": "Live trees and plants"},
    "07": {"rate": 0.05, "desc_ar": "خضروات", "desc_en": "Vegetables"},
    "08": {"rate": 0.10, "desc_ar": "فواكه ومكسرات", "desc_en": "Fruits and nuts"},
    "09": {"rate": 0.05, "desc_ar": "قهوة وشاي وتوابل", "desc_en": "Coffee, tea, spices"},
    "10": {"rate": 0.05, "desc_ar": "حبوب", "desc_en": "Cereals"},
    "11": {"rate": 0.05, "desc_ar": "منتجات الطحن", "desc_en": "Milling industry products"},
    "12": {"rate": 0.05, "desc_ar": "بذور زيتية", "desc_en": "Oil seeds"},
    "13": {"rate": 0.05, "desc_ar": "صمغ ومستخلصات", "desc_en": "Gums and resins"},
    "14": {"rate": 0.05, "desc_ar": "مواد نباتية للتضفير", "desc_en": "Vegetable plaiting materials"},
    "15": {"rate": 0.05, "desc_ar": "شحوم ودهون نباتية وحيوانية", "desc_en": "Animal/vegetable fats"},
    "16": {"rate": 0.15, "desc_ar": "محضرات لحوم وأسماك", "desc_en": "Preparations of meat/fish"},
    "17": {"rate": 0.05, "desc_ar": "سكر ومصنوعاته", "desc_en": "Sugars and confectionery"},
    "18": {"rate": 0.10, "desc_ar": "كاكاو ومستحضراته", "desc_en": "Cocoa and preparations"},
    "19": {"rate": 0.15, "desc_ar": "مستحضرات دقيق وعجين", "desc_en": "Preparations of flour"},
    "20": {"rate": 0.15, "desc_ar": "مستحضرات خضار وفواكه", "desc_en": "Preparations of vegetables/fruit"},
    "21": {"rate": 0.10, "desc_ar": "محضرات غذائية متنوعة", "desc_en": "Miscellaneous edible preparations"},
    "22": {"rate": 0.30, "desc_ar": "مشروبات كحولية وخل", "desc_en": "Beverages, spirits, vinegar"},
    "23": {"rate": 0.05, "desc_ar": "بقايا صناعة الأغذية", "desc_en": "Residues from food industries"},
    "24": {"rate": 0.25, "desc_ar": "تبغ", "desc_en": "Tobacco"},
    "25": {"rate": 0.05, "desc_ar": "ملح وكبريت وأحجار", "desc_en": "Salt, sulphur, stone"},
    "26": {"rate": 0.05, "desc_ar": "خامات معدنية", "desc_en": "Ores and slag"},
    "27": {"rate": 0.05, "desc_ar": "وقود معدني وزيوت", "desc_en": "Mineral fuels and oils"},
    "28": {"rate": 0.05, "desc_ar": "مواد كيميائية غير عضوية", "desc_en": "Inorganic chemicals"},
    "29": {"rate": 0.05, "desc_ar": "مواد كيميائية عضوية", "desc_en": "Organic chemicals"},
    "30": {"rate": 0.05, "desc_ar": "منتجات صيدلانية", "desc_en": "Pharmaceutical products"},
    "31": {"rate": 0.05, "desc_ar": "أسمدة", "desc_en": "Fertilisers"},
    "32": {"rate": 0.10, "desc_ar": "أصباغ ودهانات", "desc_en": "Tanning/dyeing extracts, paints"},
    "33": {"rate": 0.10, "desc_ar": "زيوت عطرية ومستحضرات تجميل", "desc_en": "Essential oils, cosmetics"},
    "34": {"rate": 0.10, "desc_ar": "صابون ومنظفات", "desc_en": "Soap, detergents"},
    "35": {"rate": 0.05, "desc_ar": "مواد لاصقة", "desc_en": "Albumin, glues"},
    "36": {"rate": 0.25, "desc_ar": "مواد شديدة الاشتعال", "desc_en": "Explosives, fireworks"},
    "37": {"rate": 0.10, "desc_ar": "منتجات تصوير فوتوغرافي", "desc_en": "Photographic products"},
    "38": {"rate": 0.05, "desc_ar": "منتجات كيميائية متنوعة", "desc_en": "Miscellaneous chemicals"},
    "39": {"rate": 0.05, "desc_ar": "لدائن ومصنوعاتها", "desc_en": "Plastics and articles"},
    "40": {"rate": 0.10, "desc_ar": "مطاط ومصنوعاته", "desc_en": "Rubber and articles"},
    "41": {"rate": 0.10, "desc_ar": "جلود خام", "desc_en": "Raw hides and skins"},
    "42": {"rate": 0.15, "desc_ar": "مصنوعات الجلود", "desc_en": "Articles of leather"},
    "43": {"rate": 0.10, "desc_ar": "فراء طبيعي", "desc_en": "Furskins"},
    "44": {"rate": 0.10, "desc_ar": "خشب ومصنوعاته", "desc_en": "Wood and articles"},
    "45": {"rate": 0.10, "desc_ar": "فلين ومصنوعاته", "desc_en": "Cork and articles"},
    "46": {"rate": 0.10, "desc_ar": "مصنوعات القش", "desc_en": "Plaiting materials"},
    "47": {"rate": 0.05, "desc_ar": "لب الخشب", "desc_en": "Pulp of wood"},
    "48": {"rate": 0.05, "desc_ar": "ورق وكرتون", "desc_en": "Paper and paperboard"},
    "49": {"rate": 0.05, "desc_ar": "كتب ومطبوعات", "desc_en": "Printed books"},
    "50": {"rate": 0.10, "desc_ar": "حرير", "desc_en": "Silk"},
    "51": {"rate": 0.10, "desc_ar": "صوف وشعر حيواني", "desc_en": "Wool, animal hair"},
    "52": {"rate": 0.10, "desc_ar": "قطن", "desc_en": "Cotton"},
    "53": {"rate": 0.10, "desc_ar": "ألياف نسيجية نباتية", "desc_en": "Vegetable textile fibres"},
    "54": {"rate": 0.10, "desc_ar": "خيوط اصطناعية", "desc_en": "Man-made filaments"},
    "55": {"rate": 0.10, "desc_ar": "ألياف اصطناعية", "desc_en": "Man-made staple fibres"},
    "56": {"rate": 0.10, "desc_ar": "لباد وغير منسوجات", "desc_en": "Wadding, nonwovens"},
    "57": {"rate": 0.10, "desc_ar": "سجاد", "desc_en": "Carpets"},
    "58": {"rate": 0.10, "desc_ar": "أقمشة خاصة", "desc_en": "Special woven fabrics"},
    "59": {"rate": 0.10, "desc_ar": "أقمشة مشبعة", "desc_en": "Impregnated textile fabrics"},
    "60": {"rate": 0.10, "desc_ar": "أقمشة محبوكة", "desc_en": "Knitted fabrics"},
    "61": {"rate": 0.05, "desc_ar": "ملابس محبوكة", "desc_en": "Knitted apparel"},
    "62": {"rate": 0.05, "desc_ar": "ملابس منسوجة", "desc_en": "Woven apparel"},
    "63": {"rate": 0.10, "desc_ar": "منسوجات منزلية", "desc_en": "Household textiles"},
    "64": {"rate": 0.15, "desc_ar": "أحذية", "desc_en": "Footwear"},
    "65": {"rate": 0.15, "desc_ar": "قبعات", "desc_en": "Headgear"},
    "66": {"rate": 0.10, "desc_ar": "مظلات وعصي", "desc_en": "Umbrellas"},
    "67": {"rate": 0.10, "desc_ar": "ريش مهيأ", "desc_en": "Prepared feathers"},
    "68": {"rate": 0.05, "desc_ar": "مصنوعات الحجارة والجبس", "desc_en": "Stone and plaster articles"},
    "69": {"rate": 0.10, "desc_ar": "منتجات خزفية", "desc_en": "Ceramic products"},
    "70": {"rate": 0.10, "desc_ar": "زجاج ومصنوعاته", "desc_en": "Glass and glassware"},
    "71": {"rate": 0.05, "desc_ar": "جواهر ومعادن ثمينة", "desc_en": "Precious metals and jewellery"},
    "72": {"rate": 0.05, "desc_ar": "حديد وصلب", "desc_en": "Iron and steel"},
    "73": {"rate": 0.05, "desc_ar": "مصنوعات الحديد والصلب", "desc_en": "Articles of iron/steel"},
    "74": {"rate": 0.05, "desc_ar": "نحاس ومصنوعاته", "desc_en": "Copper and articles"},
    "75": {"rate": 0.05, "desc_ar": "نيكل ومصنوعاته", "desc_en": "Nickel and articles"},
    "76": {"rate": 0.05, "desc_ar": "ألومنيوم ومصنوعاته", "desc_en": "Aluminium and articles"},
    "78": {"rate": 0.05, "desc_ar": "رصاص ومصنوعاته", "desc_en": "Lead and articles"},
    "79": {"rate": 0.05, "desc_ar": "خارصين ومصنوعاته", "desc_en": "Zinc and articles"},
    "80": {"rate": 0.05, "desc_ar": "قصدير ومصنوعاته", "desc_en": "Tin and articles"},
    "81": {"rate": 0.05, "desc_ar": "معادن شتى", "desc_en": "Other base metals"},
    "82": {"rate": 0.10, "desc_ar": "أدوات وسكاكين", "desc_en": "Tools, cutlery"},
    "83": {"rate": 0.10, "desc_ar": "مصنوعات معدنية متنوعة", "desc_en": "Miscellaneous metal articles"},
    "84": {"rate": 0.05, "desc_ar": "آلات ومعدات ميكانيكية", "desc_en": "Machinery and mechanical appliances"},
    "85": {"rate": 0.05, "desc_ar": "أجهزة كهربائية وإلكترونية", "desc_en": "Electrical machinery"},
    "86": {"rate": 0.05, "desc_ar": "قطارات وعربات", "desc_en": "Railway equipment"},
    "87": {"rate": 0.25, "desc_ar": "مركبات برية", "desc_en": "Vehicles"},
    "88": {"rate": 0.05, "desc_ar": "طائرات وسفن فضائية", "desc_en": "Aircraft"},
    "89": {"rate": 0.05, "desc_ar": "سفن وقوارب", "desc_en": "Ships and boats"},
    "90": {"rate": 0.05, "desc_ar": "أجهزة قياس وطبية وبصرية", "desc_en": "Optical, medical instruments"},
    "91": {"rate": 0.10, "desc_ar": "ساعات", "desc_en": "Clocks and watches"},
    "92": {"rate": 0.10, "desc_ar": "آلات موسيقية", "desc_en": "Musical instruments"},
    "93": {"rate": 0.30, "desc_ar": "أسلحة وذخائر", "desc_en": "Arms and ammunition"},
    "94": {"rate": 0.05, "desc_ar": "أثاث ومستلزمات", "desc_en": "Furniture"},
    "95": {"rate": 0.10, "desc_ar": "ألعاب أطفال", "desc_en": "Toys and games"},
    "96": {"rate": 0.10, "desc_ar": "مصنوعات متنوعة", "desc_en": "Miscellaneous manufactured articles"},
    "97": {"rate": 0.05, "desc_ar": "أعمال فنية وتحف", "desc_en": "Works of art"},
}

DOC_TYPES = {
    "commercial_invoice": {"ar": "فاتورة تجارية", "en": "Commercial Invoice"},
    "packing_list": {"ar": "قائمة التعبئة", "en": "Packing List"},
    "certificate_of_origin": {"ar": "شهادة المنشأ", "en": "Certificate of Origin"},
    "bill_of_lading": {"ar": "بوليصة الشحن", "en": "Bill of Lading"},
    "other": {"ar": "مستند آخر", "en": "Other"}
}

VIOLATION_TYPES = {
    "under_declaration": "تهرب جمركي - تخفيض القيمة",
    "prohibited_goods": "بضائع محظورة أو مقيدة",
    "doc_forgery": "تزوير وثائق جمركية",
    "quantity_mismatch": "عدم مطابقة الكميات",
    "hs_mismatch": "كود HS غير صحيح",
    "other": "مخالفة أخرى",
}

LIBYA_PROHIBITED_ITEMS = """
ABSOLUTELY PROHIBITED (محظور كلياً):
1. Pork products (خنزير ومشتقاته): HS 0103, 0203, 0206, 0209, 0502, 1501, 1503, 1601, 1602, 4103
2. Alcoholic beverages (مشروبات كحولية): HS 2204, 2206
3. Potassium Bromate (برومات البوتاسيوم): HS 28299021
4. Firearms & Ammunition (أسلحة وذخيرة) - unauthorized: HS 9303, 9304, 9306, 8205
5. Explosives & Fireworks private use: HS 3601, 3603, 3604
PROHIBITED CHEMICALS: Methanol HS 29051100, Acetone HS 29141100, Ammonia HS 2814, Paint Solvents HS 3814/3805
RESTRICTED (specific companies only): Petroleum HS 2709/2711/2710 (NOC only), Weapons (Security Industries only), Narcotics (auth. companies), Gas cylinders >11kg (NOC)
PROHIBITED EXPORTS: Iron scrap HS 7204/7206/7213/7215/7218/7224, Copper scrap HS 7404, Lead scrap HS 7801/7802, Aluminum HS 7602, Wood charcoal HS 4402, Cement HS 2523
"""

ARABIC_MONTHS = {
    1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو",
    7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر"
}

TIMELINE_STAGES = [
    {"key": "submitted",      "label_ar": "تقديم الطلب",         "label_en": "Request Submitted"},
    {"key": "under_review",   "label_ar": "قيد المراجعة الجمركية", "label_en": "Customs Review"},
    {"key": "approved",       "label_ar": "اعتماد ACID",          "label_en": "ACID Approved"},
    {"key": "valued",         "label_ar": "التقييم الجمركي",      "label_en": "Customs Valuation"},
    {"key": "treasury_paid",  "label_ar": "سداد الرسوم الجمركية", "label_en": "Duties Paid"},
    {"key": "gate_released",  "label_ar": "الإفراج النهائي JL38", "label_en": "Final Release (JL38)"},
]

STATUS_ORDER = {s["key"]: i for i, s in enumerate(TIMELINE_STAGES)}
