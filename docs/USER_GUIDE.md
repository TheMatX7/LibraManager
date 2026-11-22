# LibraManager — guide for demonstration

## Starting the application

1. Set `SECRET_KEY` in `.env`.
2. Optionally run `python run.py --seed-demo` only against a new database and
   save the generated credentials shown in the console.
3. Run `python run.py`, then open `http://127.0.0.1:5000/`.

The CLI alternative is `python run.py --cli`.

## Administrator

The administrator dashboard shows live totals for catalogue availability,
active/overdue loans and financial settlement. The sidebar gives access to:

- user account creation and activation state;
- catalogue, copies, readers, loans, reservations, fines and payments;
- reports and CSV export;
- configurable business settings;
- the most recent audit entries.

Use **Ustawienia** to change a permitted business parameter. The service layer
validates limits and applies the new value to future operations.

## Librarian

The librarian manages day-to-day circulation:

1. Register a reader in **Czytelnicy**.
2. Add a catalogue item in **Katalog książek**, then add a physical item in
   **Egzemplarze**.
3. In **Wypożyczenia**, select a reader and an available copy.
4. Use **Przyjmij zwrot** when the item comes back. Overdue returns create a
   fine through the normal service rules.
5. Register an amount and CASH/CARD method in **Płatności**. Do not register a
   second payment after a fine is paid; the application rejects it.

## Reader

Readers can browse the catalogue, create/cancel their own reservations and
view only their own loans, fines and payment history. They cannot access staff
reports, user administration, other readers' records or payment registration.

## Important behavior

- All forms that change data include CSRF protection.
- Messages explain rejected inputs or business rules without exposing internal
  stack traces.
- Buttons shown by the interface invoke real service operations; unavailable
  operations are not displayed to readers.
- CSV exports are generated from current data and contain no arbitrary-query
  functionality.
