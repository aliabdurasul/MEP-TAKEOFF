# START HERE — MEP Takeoff'u yerelde çalıştırma (Windows)

## Başlat

Proje klasöründe `start_app.cmd` dosyasına çift tıkla (ya da terminalde):

```powershell
.\start_app.cmd
```

Tarayıcı `http://127.0.0.1:8501` adresinde açılır. Uygulama yalnızca bu bilgisayardan erişilebilir.
Durdurmak için açılan pencereyi kapat veya `Ctrl+C`.

İlk çalıştırmada `.venv` oluşturulur ve bağımlılıklar kurulur (birkaç dakika sürer).
Python 3.11 yoksa bir kez kur, sonra yeni bir terminal aç:

```powershell
winget install -e --id Python.Python.3.11 --scope user
```

## Kullan

1. "Загрузить DXF" alanına `.dxf` dosyasını yükle (DWG desteklenmez; önce DXF'e çevir).
2. Toplam metraj, çap bazında uzunluklar, uyarılar ve katman analizi sayfada görünür.
3. Sayfanın en altındaki "Скачать Excel" ile raporu indir.

Gerçek çizim yoksa sentetik demo çizimleri oluştur (`data/demo/` altına yazılır, Git'e girmez):

```powershell
.\.venv\Scripts\python.exe tools\make_demo_drawings.py
```

| Dosya | Beklenen sonuç |
|---|---|
| `data/demo/plan_v1/plan.dxf` | 15.57 m (Ø16 5.00, DN20 2.00, UNKNOWN 8.57), 3 uyarı |
| `data/demo/plan_v2/plan.dxf` | 10.00 m (Ø25) — aynı dosya adı, farklı içerik |
| `data/demo/unknown_units.dxf` | 5,000.00 çizim birimi, `UNKNOWN_UNITS` uyarısı |

## Testler

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

Gerçek çizim testleri `data\input\MIR_OT_ANTP_R22_K2_8.dxf` yoksa atlanır (NOT RUN).
Ayrıntılar: `docs/V1_PRIVATE_VERIFICATION.md`.

## Güvenlik

- Proje çizimlerini `data\input\` altında tut; Git'e ekleme, internete veya harici servislere yükleme.
- Yüklenen dosyalar yalnızca yerelde `data\input\<sha256>\` altında saklanır.
