CREATE TABLE audit_logs (
	id INTEGER NOT NULL, 
	user_id INTEGER, 
	action VARCHAR(100) NOT NULL, 
	description TEXT, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE authors (
	id INTEGER NOT NULL, 
	first_name VARCHAR(100) NOT NULL, 
	last_name VARCHAR(100) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE book_authors (
	book_id INTEGER NOT NULL, 
	author_id INTEGER NOT NULL, 
	PRIMARY KEY (book_id, author_id), 
	FOREIGN KEY(book_id) REFERENCES books (id), 
	FOREIGN KEY(author_id) REFERENCES authors (id)
);

CREATE TABLE books (
	id INTEGER NOT NULL, 
	isbn VARCHAR(20), 
	title VARCHAR(200) NOT NULL, 
	description TEXT, 
	publisher VARCHAR(150), 
	publication_year INTEGER, 
	category_id INTEGER, 
	is_archived BOOLEAN NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT check_book_publication_year CHECK (publication_year IS NULL OR publication_year BETWEEN 1000 AND 2100), 
	CONSTRAINT check_book_title CHECK (length(trim(title)) > 0), 
	UNIQUE (isbn), 
	FOREIGN KEY(category_id) REFERENCES categories (id)
);

CREATE TABLE categories (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	description TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE copies (
	id INTEGER NOT NULL, 
	book_id INTEGER NOT NULL, 
	inventory_number VARCHAR(50) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	added_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT check_copy_status CHECK (status IN ('AVAILABLE', 'LOANED', 'RESERVED', 'DAMAGED', 'LOST')), 
	FOREIGN KEY(book_id) REFERENCES books (id), 
	UNIQUE (inventory_number)
);

CREATE TABLE fines (
	id INTEGER NOT NULL, 
	loan_id INTEGER NOT NULL, 
	amount NUMERIC(10, 2) NOT NULL, 
	paid_amount NUMERIC(10, 2) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT check_fine_amount CHECK (amount >= 0), 
	CONSTRAINT check_fine_paid_amount CHECK (paid_amount >= 0 AND paid_amount <= amount), 
	CONSTRAINT check_fine_status CHECK (status IN ('UNPAID', 'PARTIALLY_PAID', 'PAID')), 
	UNIQUE (loan_id), 
	FOREIGN KEY(loan_id) REFERENCES loans (id)
);

CREATE TABLE loans (
	id INTEGER NOT NULL, 
	copy_id INTEGER NOT NULL, 
	reader_id INTEGER NOT NULL, 
	borrowed_at DATETIME, 
	due_date DATETIME NOT NULL, 
	returned_at DATETIME, 
	status VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT check_loan_status CHECK (status IN ('ACTIVE', 'RETURNED', 'CANCELLED')), 
	FOREIGN KEY(copy_id) REFERENCES copies (id), 
	FOREIGN KEY(reader_id) REFERENCES readers (id)
);

CREATE TABLE payments (
	id INTEGER NOT NULL, 
	fine_id INTEGER NOT NULL, 
	amount NUMERIC(10, 2) NOT NULL, 
	method VARCHAR(30) NOT NULL, 
	paid_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT check_payment_amount CHECK (amount > 0), 
	CONSTRAINT check_payment_method CHECK (method IN ('CASH', 'CARD')), 
	FOREIGN KEY(fine_id) REFERENCES fines (id)
);

CREATE TABLE readers (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	card_number VARCHAR(30) NOT NULL, 
	first_name VARCHAR(80) NOT NULL, 
	last_name VARCHAR(80) NOT NULL, 
	phone VARCHAR(30), 
	registered_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT check_reader_first_name CHECK (length(trim(first_name)) > 0), 
	CONSTRAINT check_reader_last_name CHECK (length(trim(last_name)) > 0), 
	UNIQUE (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	UNIQUE (card_number)
);

CREATE TABLE reservations (
	id INTEGER NOT NULL, 
	book_id INTEGER NOT NULL, 
	reader_id INTEGER NOT NULL, 
	reserved_at DATETIME, 
	expires_at DATETIME, 
	status VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT check_reservation_status CHECK (status IN ('WAITING', 'READY', 'FULFILLED', 'CANCELLED', 'EXPIRED')), 
	FOREIGN KEY(book_id) REFERENCES books (id), 
	FOREIGN KEY(reader_id) REFERENCES readers (id)
);

CREATE TABLE settings (
	id INTEGER NOT NULL, 
	"key" VARCHAR(100) NOT NULL, 
	value VARCHAR(255) NOT NULL, 
	description TEXT, 
	PRIMARY KEY (id), 
	UNIQUE ("key")
);

CREATE TABLE users (
	id INTEGER NOT NULL, 
	username VARCHAR(80) NOT NULL, 
	email VARCHAR(120) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT check_user_role CHECK (role IN ('ADMIN', 'LIBRARIAN', 'READER')), 
	UNIQUE (username), 
	UNIQUE (email)
);