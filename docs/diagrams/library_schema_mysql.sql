CREATE TABLE `audit_logs` (
    `id` INT NOT NULL,
    `user_id` INT,
    `action` VARCHAR(100) NOT NULL,
    `description` TEXT,
    `created_at` DATETIME,
    PRIMARY KEY (`id`)
);

CREATE TABLE `authors` (
    `id` INT NOT NULL,
    `first_name` VARCHAR(100) NOT NULL,
    `last_name` VARCHAR(100) NOT NULL,
    PRIMARY KEY (`id`)
);

CREATE TABLE `book_authors` (
    `book_id` INT NOT NULL,
    `author_id` INT NOT NULL,
    PRIMARY KEY (`book_id`, `author_id`)
);

CREATE TABLE `books` (
    `id` INT NOT NULL,
    `isbn` VARCHAR(20),
    `title` VARCHAR(200) NOT NULL,
    `description` TEXT,
    `publisher` VARCHAR(150),
    `publication_year` INT,
    `category_id` INT,
    `is_archived` TINYINT(1) NOT NULL,
    `created_at` DATETIME,
    PRIMARY KEY (`id`),
    UNIQUE (`isbn`)
);

CREATE TABLE `categories` (
    `id` INT NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `description` TEXT,
    PRIMARY KEY (`id`),
    UNIQUE (`name`)
);

CREATE TABLE `copies` (
    `id` INT NOT NULL,
    `book_id` INT NOT NULL,
    `inventory_number` VARCHAR(50) NOT NULL,
    `status` VARCHAR(20) NOT NULL,
    `added_at` DATETIME,
    PRIMARY KEY (`id`),
    UNIQUE (`inventory_number`)
);

CREATE TABLE `fines` (
    `id` INT NOT NULL,
    `loan_id` INT NOT NULL,
    `amount` DECIMAL(10, 2) NOT NULL,
    `paid_amount` DECIMAL(10, 2) NOT NULL,
    `status` VARCHAR(20) NOT NULL,
    `created_at` DATETIME,
    PRIMARY KEY (`id`),
    UNIQUE (`loan_id`)
);

CREATE TABLE `loans` (
    `id` INT NOT NULL,
    `copy_id` INT NOT NULL,
    `reader_id` INT NOT NULL,
    `borrowed_at` DATETIME,
    `due_date` DATETIME NOT NULL,
    `returned_at` DATETIME,
    `status` VARCHAR(20) NOT NULL,
    PRIMARY KEY (`id`)
);

CREATE TABLE `payments` (
    `id` INT NOT NULL,
    `fine_id` INT NOT NULL,
    `amount` DECIMAL(10, 2) NOT NULL,
    `method` VARCHAR(30) NOT NULL,
    `paid_at` DATETIME,
    PRIMARY KEY (`id`)
);

CREATE TABLE `readers` (
    `id` INT NOT NULL,
    `user_id` INT NOT NULL,
    `card_number` VARCHAR(30) NOT NULL,
    `first_name` VARCHAR(80) NOT NULL,
    `last_name` VARCHAR(80) NOT NULL,
    `phone` VARCHAR(30),
    `registered_at` DATETIME,
    PRIMARY KEY (`id`),
    UNIQUE (`card_number`),
    UNIQUE (`user_id`)
);

CREATE TABLE `reservations` (
    `id` INT NOT NULL,
    `book_id` INT NOT NULL,
    `reader_id` INT NOT NULL,
    `reserved_at` DATETIME,
    `expires_at` DATETIME,
    `status` VARCHAR(20) NOT NULL,
    PRIMARY KEY (`id`)
);

CREATE TABLE `settings` (
    `id` INT NOT NULL,
    `key` VARCHAR(100) NOT NULL,
    `value` VARCHAR(255) NOT NULL,
    `description` TEXT,
    PRIMARY KEY (`id`),
    UNIQUE (`key`)
);

CREATE TABLE `users` (
    `id` INT NOT NULL,
    `username` VARCHAR(80) NOT NULL,
    `email` VARCHAR(120) NOT NULL,
    `password_hash` VARCHAR(255) NOT NULL,
    `role` VARCHAR(20) NOT NULL,
    `is_active` TINYINT(1) NOT NULL,
    `created_at` DATETIME,
    PRIMARY KEY (`id`),
    UNIQUE (`email`),
    UNIQUE (`username`)
);

ALTER TABLE `audit_logs` ADD CONSTRAINT `fk_audit_logs_0` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `book_authors` ADD CONSTRAINT `fk_book_authors_0` FOREIGN KEY (`author_id`) REFERENCES `authors` (`id`);

ALTER TABLE `book_authors` ADD CONSTRAINT `fk_book_authors_1` FOREIGN KEY (`book_id`) REFERENCES `books` (`id`);

ALTER TABLE `books` ADD CONSTRAINT `fk_books_0` FOREIGN KEY (`category_id`) REFERENCES `categories` (`id`);

ALTER TABLE `copies` ADD CONSTRAINT `fk_copies_0` FOREIGN KEY (`book_id`) REFERENCES `books` (`id`);

ALTER TABLE `fines` ADD CONSTRAINT `fk_fines_0` FOREIGN KEY (`loan_id`) REFERENCES `loans` (`id`);

ALTER TABLE `loans` ADD CONSTRAINT `fk_loans_0` FOREIGN KEY (`reader_id`) REFERENCES `readers` (`id`);

ALTER TABLE `loans` ADD CONSTRAINT `fk_loans_1` FOREIGN KEY (`copy_id`) REFERENCES `copies` (`id`);

ALTER TABLE `payments` ADD CONSTRAINT `fk_payments_0` FOREIGN KEY (`fine_id`) REFERENCES `fines` (`id`);

ALTER TABLE `readers` ADD CONSTRAINT `fk_readers_0` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `reservations` ADD CONSTRAINT `fk_reservations_0` FOREIGN KEY (`reader_id`) REFERENCES `readers` (`id`);

ALTER TABLE `reservations` ADD CONSTRAINT `fk_reservations_1` FOREIGN KEY (`book_id`) REFERENCES `books` (`id`);