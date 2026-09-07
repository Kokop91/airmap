# Zadanie: Faza 1 — Szkielet WifiScanner (Windows + Linux)

## Kontekst projektu
Budujemy wieloplatformową (Windows + Linux) aplikację do analizy sieci WiFi:
skanowanie okolicznych access pointów, wizualizacja zajętości kanałów,
graf logiczny sieci, historia zmian w czasie. Backend: Python (FastAPI
w kolejnych fazach). Frontend: web (Plotly.js / vis.js) w kolejnych fazach.

To jest **pierwszy, samodzielny krok**: warstwa skanowania WiFi, bez
backendu i frontendu. Ma być w pełni testowalna z linii poleceń.

## Cel tej fazy
Stworzyć wspólny interfejs do skanowania sieci WiFi, który pod spodem
ma dwie różne implementacje (Windows przez `netsh`, Linux przez `nmcli`),
ale na zewnątrz wygląda identycznie i zwraca ujednolicone dane.

## Wymagania funkcjonalne

### 1. Struktura danych `NetworkInfo`
Dataclass reprezentująca pojedynczą wykrytą sieć, z polami:
- `ssid: str`
- `bssid: str` (adres MAC access pointa)
- `channel: int`
- `frequency_mhz: int`
- `band: str` (np. "2.4GHz" / "5GHz" / "6GHz")
- `signal_dbm: int | None` (siła sygnału w dBm, jeśli dostępna)
- `signal_percent: int | None` (siła sygnału w %, jeśli to jedyne co
  dostarcza dany system)
- `security: str` (np. "WPA2", "WPA3", "Open", "Unknown")
- `timestamp: datetime` (moment wykonania skanu)

Jeśli dany system operacyjny nie dostarcza jakiegoś pola — ustaw `None`
zamiast zgadywać albo wymyślać wartość.

### 2. Abstrakcyjna klasa bazowa `WifiScanner`
- Metoda abstrakcyjna `scan() -> list[NetworkInfo]`
- Metoda `is_available() -> bool` — sprawdza, czy narzędzie systemowe
  (nmcli/netsh) jest w ogóle dostępne w PATH, zanim spróbujemy skanować
- Użyj `abc.ABC` + `@abstractmethod`

### 3. Implementacja `LinuxWifiScanner`
- Używa `nmcli --terse --fields SSID,BSSID,CHAN,FREQ,SIGNAL,SECURITY dev wifi list`
  (dobierz dokładne pola pod potrzeby `NetworkInfo`)
- Parsowanie formatu `--terse` (pola rozdzielone dwukropkiem — uważaj,
  BSSID też zawiera dwukropki, więc trzeba to obsłużyć poprawnie,
  najlepiej sprawdzić realny output `nmcli` i dopasować parser do niego)
- Uruchamianie przez `subprocess.run`, z `timeout` (np. 10s) i sensownym
  komunikatem błędu jeśli komenda zawiedzie

### 4. Implementacja `WindowsWifiScanner`
- Używa `netsh wlan show networks mode=bssid`
- **Uwaga na lokalizację**: output `netsh` może być po polsku (inne
  nagłówki niż angielskie). Zaimplementuj wykrywanie języka nagłówków
  LUB wymuszenie angielskiego (sprawdź, czy da się to zrobić flagą,
  a jeśli nie — obsłuż PL i EN jako dwa warianty nagłówków)
- Parsowanie tekstowego outputu (regex albo parsowanie linia po linii
  po wcięciach — `netsh` nie ma trybu maszynowego jak `nmcli --terse`)
- Ten sam standard błędów/timeoutów co w wersji Linux

### 5. Fabryka `get_scanner() -> WifiScanner`
- Wybiera implementację na podstawie `platform.system()`
  (`"Windows"` → `WindowsWifiScanner`, `"Linux"` → `LinuxWifiScanner`)
- Rzuca czytelny wyjątek dla nieobsługiwanego systemu (np. macOS na razie)

### 6. Prosty runner testowy (`main.py` lub `if __name__ == "__main__"`)
- Pobiera scanner przez fabrykę
- Sprawdza `is_available()`, jeśli False — czytelny komunikat i wyjście
- Wykonuje `scan()` i wypisuje wynik w czytelnej tabeli w konsoli
  (SSID, kanał, pasmo, sygnał, security)

## Wymagania niefunkcjonalne
- Python 3.11+, tylko biblioteka standardowa (bez zewnętrznych
  pakietów w tej fazie — to ma być lekki, łatwy do przetestowania
  moduł)
- Typowanie (type hints) na wszystkich publicznych metodach
- Docstringi wyjaśniające specyfikę parsowania (przyszły ja/inny
  developer musi zrozumieć czemu parser wygląda jak wygląda)
- Obsługa błędów: brak `nmcli`/`netsh`, brak uprawnień, pusty wynik
  skanu (0 sieci w zasięgu) — to nie powinno wywalać wyjątku, tylko
  zwrócić pustą listę z logiem ostrzegawczym

## Struktura plików (proponowana)
```
wifi_scanner/
├── __init__.py
├── models.py          # NetworkInfo
├── base.py            # WifiScanner (ABC)
├── linux_scanner.py   # LinuxWifiScanner
├── windows_scanner.py # WindowsWifiScanner
├── factory.py         # get_scanner()
└── main.py            # runner testowy
```

## Czego NIE robić w tej fazie
- Bez bazy danych, bez zapisu historii
- Bez backendu (FastAPI) ani frontendu
- Bez deautentykacji, trybu monitor, przechwytywania ruchu — tylko
  pasywny odczyt listy sieci przez standardowe narzędzia systemowe
- Bez wsparcia macOS (na razie)

## Kryterium akceptacji
Uruchomienie `python -m wifi_scanner.main` na Linuksie z `nmcli`
zainstalowanym wypisuje listę realnie widocznych sieci WiFi z sensownymi
danymi w każdej kolumnie. Na Windows analogicznie z `netsh`. Jeśli nie
masz w tej chwili dostępu do drugiego systemu do testów — zaimplementuj
obie wersje, ale jasno zaznacz w odpowiedzi, która była faktycznie
przetestowana na żywym systemie, a która tylko na podstawie
udokumentowanego formatu outputu.
