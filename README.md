# SE Havacılık OEE

Haas CNC tezgahlarından **MTConnect** üzerinden veri toplayıp **InfluxDB**'ye
yazan ve **Grafana** üzerinden raporlayan Docker tabanlı boru hattı.

- **Veri toplama**: Python collector, MTConnect XML → InfluxDB.
- **Görselleştirme**: Grafana ile günlük / haftalık / aylık state
  (active / running / stopped / offline) yüzdeleri, program çalışma
  süresi ve üretilen parça sayısı.

## Mimari

```text
┌──────────────────────┐   HTTP/XML (MTConnect)   ┌──────────────────┐   Line Protocol   ┌──────────────┐   Flux   ┌─────────┐
│ Haas Tezgahları      │ ───────────────────────► │ collector (Py)   │ ────────────────► │ InfluxDB 2.x │ ───────► │ Grafana │
│ (5 adet, port 8082)  │   /current  her ~2 sn    │  Docker konteyner│                   │  Docker      │          │  Docker │
└──────────────────────┘                          └──────────────────┘                   └──────────────┘          └─────────┘
```

- **collector**: `machines.json` listesindeki her tezgahın
  `http://<host>:8082/current` MTConnect endpoint'ini periyodik olarak
  çeker, XML'i ayrıştırır ve InfluxDB'ye yazar.
- **influxdb**: InfluxDB 2.7. UI: `http://localhost:8086`.
- **grafana**: Grafana OSS 11.3. UI: `http://localhost:3000`. Datasource
  ve dashboard'lar `grafana/provisioning/` ile **kod-olarak** yüklenir.
- Üçü de `docker-compose` ile birlikte çalışır.

## Tezgahlar (`machines.json`)

| ID      | Ad        | Model                       | IP             |
| ------- | --------- | --------------------------- | -------------- |
| vf6     | VF-6/40   | Haas VF-6/40 · 3-axis mill  | 192.168.1.113  |
| vf4     | VF-4      | Haas VF-4 · 3-axis mill     | 192.168.1.115  |
| umc400  | UMC-400   | Haas UMC-400 · 5-axis mill  | 192.168.1.114  |
| umc750  | UMC-750   | Haas UMC-750 · 5-axis mill  | 192.168.1.116  |
| st10    | ST-10     | Haas ST-10 · Lathe          | 192.168.1.112  |

Tüm tezgahların MTConnect agent'ı port **8082** üzerinden hizmet veriyor.

## Hızlı başlangıç

> Gereksinim: Docker Desktop. Tezgahların IP'lerine ulaşılabilen bir
> ağda olmalısınız (192.168.1.0/24).

```powershell
# 1) Reposu klonla
git clone https://github.com/serkankose77/SE-HAVACILIK-OEE.git
cd SE-HAVACILIK-OEE

# 2) Ortam değişkenlerini hazırla
Copy-Item .env.example .env
# .env dosyasını açıp INFLUX_PASSWORD, INFLUX_TOKEN ve GRAFANA_ADMIN_PASSWORD değerlerini doldur

# 3) Ayağa kaldır
docker compose up -d --build

# 4) Logları izle
docker compose logs -f collector
```

InfluxDB UI: <http://localhost:8086>

- Kullanıcı: `.env` içindeki `INFLUX_USERNAME`
- Şifre: `.env` içindeki `INFLUX_PASSWORD`
- Org: `se-havacilik` (varsayılan)
- Bucket: `mtconnect` (varsayılan)

Grafana UI: <http://localhost:3000>

- Kullanıcı: `.env` içindeki `GRAFANA_ADMIN_USER` (varsayılan `admin`)
- Şifre: `.env` içindeki `GRAFANA_ADMIN_PASSWORD`
- Açılışta sol menüden **Dashboards → OEE → SE Havacılık - Tezgah OEE Genel Bakış** ile dashboard'a gidin.

## Toplanan veri

Collector her bir MTConnect DataItem'ı ayrı bir nokta olarak yazar.

**Measurement**: `mtconnect`

**Tag'ler**:
- `machine_id` — `vf6`, `vf4`, `umc400`, `umc750`, `st10`
- `machine_name` — `VF-6/40`, `VF-4`, ...
- `machine_type` — `mill` veya `lathe`
- `category` — `Events`, `Samples`, `Condition`
- `item_type` — XML eleman adı (`Availability`, `Execution`, `PathFeedrate`, ...)
- `name` — DataItem adı (`avail`, `execution`, `Frt`, `Sload`, `PartCount`, ...)
- `component` — Bileşen adı (`Controller`, `Path`, `Axes`, ...)
- `sub_type` — `ACTUAL`, `COMMANDED`, `OVERRIDE`, ... (varsa)
- `condition_type` — `SYSTEM`, `LOGIC_PROGRAM`, ... (yalnızca Condition)

**Field'lar**:
- `value` (float) — Sayısal Sample değerleri (feedrate, spindle load, eksen
  pozisyonu, vb.)
- `value_str` (string) — Event/Condition değerleri (`AUTOMATIC`, `ACTIVE`,
  `AVAILABLE`, ...) ve `UNAVAILABLE` durumundaki Sample değerleri
- `state` (string) — Condition için kondisyon durumu
  (`Normal` / `Warning` / `Fault` / `Unavailable`)

Ek olarak `mtconnect_status` measurement'ı her döngüde tezgahın HTTP
ulaşılabilirliğini (`reachable=true|false`) yazar; bunu Availability
hesaplarken kullanabilirsiniz.

## Örnek Flux sorguları

**Son durumdaki Execution değerleri:**
```flux
from(bucket: "mtconnect")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "mtconnect")
  |> filter(fn: (r) => r.name == "execution")
  |> filter(fn: (r) => r._field == "value_str")
  |> last()
```

**Spindle load zaman serisi (UMC-750):**
```flux
from(bucket: "mtconnect")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "mtconnect")
  |> filter(fn: (r) => r.machine_id == "umc750")
  |> filter(fn: (r) => r.name == "Sload" and r._field == "value")
```

**Tezgah çevrimiçi kalma oranı (son 24 saat):**
```flux
from(bucket: "mtconnect")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "mtconnect_status")
  |> filter(fn: (r) => r._field == "reachable")
  |> mean()
  |> group(columns: ["machine_id"])
```

## Yapılandırma (`.env`)

| Değişken                   | Açıklama                                         | Varsayılan        |
| -------------------------- | ------------------------------------------------ | ----------------- |
| `INFLUX_USERNAME`          | İlk kurulumda oluşturulan admin kullanıcı        | `admin`           |
| `INFLUX_PASSWORD`          | Admin şifresi (zorunlu, güçlü olsun)             | —                 |
| `INFLUX_ORG`               | InfluxDB organization adı                        | `se-havacilik`    |
| `INFLUX_BUCKET`            | Veri yazılacak bucket                            | `mtconnect`       |
| `INFLUX_TOKEN`             | Admin token (zorunlu, uzun rastgele dize)        | —                 |
| `INFLUX_RETENTION`         | Bucket retention (saniye, 0 = sonsuz)            | `0`               |
| `INFLUX_PORT`              | Host'ta açılacak port                            | `8086`            |
| `POLL_INTERVAL`            | Her tezgahın saniyede bir kez sorgulanması       | `2`               |
| `HTTP_TIMEOUT`             | MTConnect HTTP zaman aşımı (sn)                  | `5`               |
| `LOG_LEVEL`                | `DEBUG` / `INFO` / `WARNING`                     | `INFO`            |
| `GRAFANA_PORT`             | Host'ta Grafana UI portu                         | `3000`            |
| `GRAFANA_ADMIN_USER`       | Grafana admin kullanıcı                          | `admin`           |
| `GRAFANA_ADMIN_PASSWORD`   | Grafana admin şifresi (zorunlu)                  | —                 |

## Tezgah listesini düzenlemek

`machines.json` dosyasını düzenleyip `docker compose restart collector`
ile değişikliği uygula. Format:

```json
{
  "<id>": {
    "name":  "<insan-okur-isim>",
    "model": "<model-aciklamasi>",
    "host":  "<ip-veya-hostname>",
    "port":  8082,
    "type":  "mill | lathe"
  }
}
```

## Sorun giderme

**Collector "fetch ... failed" yazıyor.** Tezgah ağı erişilemez ya da
MTConnect agent çalışmıyor olabilir. Test edin:
```powershell
curl http://192.168.1.113:8082/current
```

**InfluxDB sağlıksız (unhealthy).** İlk kurulum tamamlanmamış olabilir.
`docker compose logs influxdb` çıktısına bakın. Sıfırdan başlamak için:
```powershell
docker compose down -v
docker compose up -d
```
> Uyarı: `-v` bayrağı tüm InfluxDB verisini siler.

**Token geçersiz.** `.env` içindeki `INFLUX_TOKEN` ile bucket'a erişen
collector aynı token'ı kullanır. Token'ı değiştirmek için bucket'ı
sıfırlamanız gerekir (`down -v`) veya Influx UI'dan yeni bir token
oluşturup `.env` ve `docker compose restart collector` yapın.

## Grafana panosu

Provisioning ile otomatik yüklenen dashboard: **OEE → SE Havacılık - Tezgah
OEE Genel Bakış** (`uid=oee-overview`).

### State haritalaması

Dashboard sorguları MTConnect verisinden 4 state üretir:

| Etiket    | Renk    | Koşul                                                           |
| --------- | ------- | --------------------------------------------------------------- |
| `OFFLINE` | Kırmızı | `mtconnect_status.reachable=false` (MTConnect agent erişilemez) |
| `STOPPED` | Turuncu | `Execution=UNAVAILABLE` (tezgah açık ama kontrolör veri vermiyor)|
| `RUNNING` | Mavi    | `Execution IN (READY, STOPPED, INTERRUPTED, FEED_HOLD)` (idle)  |
| `ACTIVE`  | Yeşil   | `Execution=ACTIVE` (program in-cycle)                           |

### Paneller

1. **Tezgah anlık durumu** — son 10 dakikadaki en güncel state, 5 tezgah
   için renkli stat panel.
2. **State yüzdeleri (tezgah başına)** — seçili zaman aralığında her
   tezgahın 4 state'te geçirdiği zaman yüzdesi.
3. **Toplam state dağılımı** — tüm tezgahların toplam dağılımı (donut).
4. **State zaman çizelgesi** — tezgah × zaman ızgarasında state-timeline.
5. **Program çalışma süresi** — tezgah/program kombinasyonu için toplam
   süre tablosu.
6. **Aralıkta üretilen parça** — tezgah başına `PartCount` değeri (delta:
   son − ilk).

### Tarih aralığı

Sağ üstteki Grafana time-picker'ından preset seçin:

- **Son 24 saat** (`now-24h`) → günlük rapor
- **Son 7 gün** (`now-7d`) → haftalık rapor
- **Son 30 gün** (`now-30d`) → aylık rapor

Custom aralık için takvimden başlangıç/bitiş seçin. Yenileme aralığı
varsayılan **30 sn**.

### Dashboard düzenleme

Provisioning klasöründeki JSON tek doğru kaynaktır:

```powershell
# Düzenleme
notepad grafana\dashboards\oee-overview.json

# Grafana 30 sn'de bir yeniden yükler; manuel restart gerekmez
docker compose restart grafana
```

Grafana UI'dan yapılan değişiklikler `allowUiUpdates: true` ile geçici
olarak görünür; kalıcı olması için JSON'u export edip dosyaya yazın.

## Yol haritası

- [x] MTConnect → InfluxDB veri toplama
- [x] Grafana panosu — state yüzdeleri + program süresi + parça sayısı
- [ ] OEE matematiği: Availability × Performance × Quality (formülize)
- [ ] Vardiya / planlı duruş takvimi entegrasyonu
- [ ] Alarm / bildirim entegrasyonu

## Lisans

İç kullanım — SE Havacılık.
