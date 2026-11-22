# LibraManager — raport odbioru technicznego

Data odbioru: 22 listopada 2026 r.

## Zakres

Zweryfikowano warstwę usług, kompletny CLI, backend Flask, responsywny
frontend, RBAC/CSRF, dane demonstracyjne, eksporty raportów oraz testy
systemowe i integracyjne. Nie zmieniano istniejącej bazy
`database/library.db`; testy korzystają z baz tymczasowych lub in-memory.

## Wynik

Projekt spełnia założony zakres demonstracyjny i pozostaje gotowy do prezentacji
akademickiej. Trasy WWW i menu CLI nie zawierają własnej logiki biznesowej:
wywołują `app.services`, a usługi korzystają z repozytoriów i modeli SQLAlchemy.

Pełna regresja: **1750 testów zakończonych powodzeniem**, 219,37 s, pokrycie
`app/services` **97%** (branch coverage). Szczegóły i pliki JUnit/coverage
znajdują się w [TEST_REPORT.md](TEST_REPORT.md).

Zweryfikowane moduły CRUD obejmują książki (edycja/archiwizacja/przywracanie),
autorów, kategorie, egzemplarze, czytelników i użytkowników. Operacje
wypożyczeń, zwrotów, rezerwacji, kar, płatności, raportów, ustawień i audytu są
dostępne zgodnie z rolą.

## Kontrole bezpieczeństwa i integralności

- RBAC w trasach i publicznych metodach usług; czytelnik nie może odczytać
  cudzych zasobów (IDOR).
- CSRF na formularzach POST, rotacja sesji po logowaniu, `HttpOnly`,
  `SameSite=Lax`, CSP, `X-Frame-Options`, `nosniff` i polityka referrerów.
- Pięć błędnych logowań z jednego adresu w oknie pięciu minut blokuje kolejną
  próbę; wdrożenie wieloprocesowe wymaga zewnętrznego limitera.
- Płatności używają `Decimal`, warunkowej aktualizacji fine, jednego
  rollbackowalnego transakcyjnie zapisu płatność–kara–audyt oraz testu dwóch
  niezależnych sesji SQLite.
- CSV neutralizuje komórki rozpoczynające się od `=`, `+`, `-` i `@`.
- Produkcja bez `SECRET_KEY` nie startuje; strony błędów HTML nie ujawniają
  tracebacków.

## QA interfejsu

Wykonano ręczny przegląd w natywnym Chrome na uruchomionej bazie demo:
logowanie, panel administratora, katalog, raporty, wylogowanie i panel
czytelnika. Wszystkie obserwowane przyciski i przejścia działały. Zapisano
zrzut [reader-dashboard.png](screenshots/acceptance/reader-dashboard.png).
Reguły CSS dla szerokości desktop/tablet/mobile są objęte testami HTTP i
przeglądem kodu; pełne pomiary pikselowe wymagają zewnętrznego runnera
przeglądarkowego.

## Artefakty

- `docs/coverage/final/index.html` i `coverage.xml` — pokrycie kodu usług,
- `docs/test_reports/final.xml` — JUnit XML,
- `docs/PRESENTATION_GUIDE.md` — scenariusz prezentacji,
- `docs/SECURITY.md` — wymagania wdrożeniowe,
- `backup/2026-11-22-final-acceptance-pre-qa-polish/` — kopia źródeł przed
  finalnymi poprawkami odbiorowymi.

## Ograniczenia wdrożeniowe

Wersja jest przeznaczona do demonstracji lokalnej. Przed użyciem produkcyjnym
należy dodać WSGI/reverse proxy z HTTPS, wspólny limiter logowania, proces
backupów SQLite oraz monitorowanie. Nie ma integracji z zewnętrznym operatorem
płatności ani odzyskiwania hasła przez e-mail.
