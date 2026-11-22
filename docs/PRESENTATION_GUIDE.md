# LibraManager — scenariusz prezentacji

Ten scenariusz prowadzi przez kompletne demo systemu w około 10–15 minut.
Interfejs CLI i panel WWW korzystają z tych samych usług oraz bazy SQLite.

## Start

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py --seed-demo
.\.venv\Scripts\python.exe run.py
```

Polecenie `--seed-demo` działa wyłącznie na pustej bazie i wypisuje jednorazowe,
losowe hasła trzech kont. Należy przekazać je prowadzącemu wyłącznie lokalnie;
nie są zapisane w repozytorium. Panel jest dostępny pod adresem
`http://127.0.0.1:5000/`.

## Przebieg demonstracji WWW

1. Zaloguj się jako administrator i pokaż panel główny: aktywne wypożyczenia,
   należności, stan egzemplarzy i szybkie działania.
2. Otwórz **Katalog**, wyszukaj książkę, przejdź do szczegółów, edytuj ją oraz
   pokaż archiwizację/przywracanie.
3. W **Czytelnikach** zademonstruj rejestrację, a następnie w **Wypożyczeniach**
   wybierz czytelnika i dostępny egzemplarz. Zwrot wykonuje się przyciskiem
   **Przyjmij zwrot**.
4. W **Płatnościach** zarejestruj częściową kwotę kary. System aktualizuje
   saldo, status kary i audyt w jednej transakcji.
5. Otwórz **Raporty** i pobierz raport CSV. Pokaż także **Ustawienia** oraz
   **Audyt** jako funkcje dostępne wyłącznie administratorowi.
6. Wyloguj się, zaloguj jako bibliotekarz i pokaż ograniczony panel bez
   administracji użytkownikami i ustawieniami.
7. Zaloguj się jako czytelnik. Dostępne są wyłącznie własne wypożyczenia,
   rezerwacje, kary, płatności i katalog; formularz rejestracji płatności jest
   niedostępny.

## Przebieg demonstracji CLI

```powershell
.\.venv\Scripts\python.exe run.py --cli
```

CLI prowadzi przez logowanie, katalog, wypożyczenia, rezerwacje, płatności,
profil oraz raporty zależnie od roli. Każda operacja jest delegowana do tych
samych klas `app.services`, co trasy Flask.

## Wskazówki prezentacyjne

- Używaj wygenerowanych danych demonstracyjnych, nigdy produkcyjnej bazy.
- Przy operacjach finansowych pokaż, że nadpłata, niepoprawna kwota i druga
  płatność są odrzucane bez zmiany salda.
- Pokaż responsywność przez zwężenie okna: menu boczne przechodzi w układ
  mobilny, a tabele pozostają przewijalne poziomo.
- Po demonstracji zatrzymaj serwer `Ctrl+C`; baza demonstracyjna jest izolowana.

## Materiały wizualne

- [zrzut panelu czytelnika](screenshots/acceptance/reader-dashboard.png)
- [raport testowy](TEST_REPORT.md)
- [raport odbiorowy](ACCEPTANCE_REPORT.md)
