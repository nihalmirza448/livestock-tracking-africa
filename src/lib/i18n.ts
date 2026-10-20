export const locales = ["ar", "en"] as const;
export type Locale = (typeof locales)[number];

export function isLocale(value: string): value is Locale {
  return (locales as readonly string[]).includes(value);
}

const dict = {
  en: {
    appName: "SLEWCIS",
    tagline: "Livestock movement and climate intelligence · Phase 1 prototype",
    overview: "Conditions",
    sources: "Data sources",
    switchLang: "العربية",
    pilotArea: "Pilot area",
    latest: "Latest",
    noData: "No data yet. The ingest job has not run for this source.",
    source: "Source",
    fallbackUsed: "Primary source delayed. Showing fallback:",
    validation: "Validation",
    lastValid: "Last valid date",
    unvalidated: "Unvalidated",
    in_review: "In review",
    validated: "Validated",
    rejected: "Rejected",
    trend: "Last 90 observations",
    boundaryNote: "Boundary is an approximate bounding box until the official admin boundary is loaded.",
    status: "Status",
    lastRun: "Last run",
    lastObs: "Latest data",
    cadence: "Cadence",
    role: "Role",
    never: "Never",
    disabled: "Disabled",
    precipitation: "Rainfall",
    ndvi: "Vegetation (NDVI)",
    soil_moisture_rootzone: "Root-zone soil moisture",
    soil_moisture_surface: "Surface soil moisture",
    groundwater_storage: "Groundwater storage",
    water_storage_anomaly: "Water storage anomaly (GRACE)",
    evapotranspiration: "Evapotranspiration",
    air_temperature: "Air temperature",
    surface_temperature: "Land surface temperature",
    elevation: "Elevation",
  },
  ar: {
    appName: "SLEWCIS",
    tagline: "معلومات حركة الماشية والمناخ · نموذج أولي للمرحلة الأولى",
    overview: "الأوضاع",
    sources: "مصادر البيانات",
    switchLang: "English",
    pilotArea: "المنطقة التجريبية",
    latest: "الأحدث",
    noData: "لا توجد بيانات بعد. لم تعمل مهمة الجلب لهذا المصدر.",
    source: "المصدر",
    fallbackUsed: "المصدر الرئيسي متأخر. يُعرض المصدر البديل:",
    validation: "التحقق",
    lastValid: "آخر تاريخ صالح",
    unvalidated: "غير متحقق منه",
    in_review: "قيد المراجعة",
    validated: "متحقق منه",
    rejected: "مرفوض",
    trend: "آخر 90 قراءة",
    boundaryNote: "الحدود مستطيل تقريبي إلى حين تحميل الحدود الإدارية الرسمية.",
    status: "الحالة",
    lastRun: "آخر تشغيل",
    lastObs: "أحدث بيانات",
    cadence: "التواتر",
    role: "الدور",
    never: "لم يعمل",
    disabled: "معطّل",
    precipitation: "الأمطار",
    ndvi: "الغطاء النباتي (NDVI)",
    soil_moisture_rootzone: "رطوبة التربة في منطقة الجذور",
    soil_moisture_surface: "رطوبة التربة السطحية",
    groundwater_storage: "مخزون المياه الجوفية",
    water_storage_anomaly: "شذوذ مخزون المياه (GRACE)",
    evapotranspiration: "التبخر النتحي",
    air_temperature: "درجة حرارة الهواء",
    surface_temperature: "درجة حرارة سطح الأرض",
    elevation: "الارتفاع",
  },
} as const;

export type Messages = { [K in keyof (typeof dict)["en"]]: string };

export function t(lang: Locale): Messages {
  return dict[lang];
}
