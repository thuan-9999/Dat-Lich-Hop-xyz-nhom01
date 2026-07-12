DROP TABLE IF EXISTS meeting_participants;
DROP TABLE IF EXISTS meetings;
DROP TABLE IF EXISTS rooms;
DROP TABLE IF EXISTS employees;

CREATE TABLE employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'employee',   -- employee / manager / admin
    is_locked INTEGER NOT NULL DEFAULT 0     -- 0 = hoạt động, 1 = bị khóa
);

CREATE TABLE rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    capacity INTEGER NOT NULL,
    equipment TEXT,
    status TEXT NOT NULL DEFAULT 'active'   -- active / maintenance / deleted
);

CREATE TABLE meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    room_id INTEGER NOT NULL,
    start_time TEXT NOT NULL,     -- ISO format: YYYY-MM-DD HH:MM
    end_time TEXT NOT NULL,
    description TEXT,
    creator_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',   -- active / cancelled
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (room_id) REFERENCES rooms(id),
    FOREIGN KEY (creator_id) REFERENCES employees(id)
);

CREATE TABLE meeting_participants (
    meeting_id INTEGER NOT NULL,
    employee_id INTEGER NOT NULL,
    response TEXT NOT NULL DEFAULT 'pending',  -- pending / accepted / declined
    PRIMARY KEY (meeting_id, employee_id),
    FOREIGN KEY (meeting_id) REFERENCES meetings(id),
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);

CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,       -- người nhận thông báo
    meeting_id INTEGER,                 -- cuộc họp liên quan (có thể NULL)
    message TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
);

-- Dữ liệu mẫu (seed data)
-- Mật khẩu demo cho tất cả tài khoản mẫu: 123456
-- (băm bằng pbkdf2:sha256 - werkzeug.security.generate_password_hash)
-- Phân quyền demo: Đức = admin, Thuận (Minh) = manager, Thuận (Hữu) = employee
INSERT INTO employees (name, email, password_hash, role, is_locked) VALUES
    ('Dương Minh Đức', 'duc@xyz.com', 'pbkdf2:sha256:1000000$gfpBUESgVMSxtT4P$393dc322e41dbf77c46c00bb821fba064bcf1b6b828ee6a9bb3a041d717d1199', 'admin', 0),
    ('Nguyễn Minh Thuận', 'minhthuan@xyz.com', 'pbkdf2:sha256:1000000$gfpBUESgVMSxtT4P$393dc322e41dbf77c46c00bb821fba064bcf1b6b828ee6a9bb3a041d717d1199', 'manager', 0),
    ('Nguyễn Hữu Thuận', 'huuthuan@xyz.com', 'pbkdf2:sha256:1000000$gfpBUESgVMSxtT4P$393dc322e41dbf77c46c00bb821fba064bcf1b6b828ee6a9bb3a041d717d1199', 'employee', 0);

INSERT INTO rooms (name, capacity, equipment, status) VALUES
    ('Phòng A', 20, 'Máy chiếu, Camera, Micro', 'active'),
    ('Phòng B', 10, 'Máy chiếu, Micro', 'active'),
    ('Phòng C', 6, 'TV màn hình, Micro', 'active');

INSERT INTO meetings (title, room_id, start_time, end_time, description, creator_id, status) VALUES
    ('Họp Sprint Planning', 1, '2026-07-13 09:00', '2026-07-13 10:00', 'Lên kế hoạch Sprint tuần tới', 1, 'active');

INSERT INTO meeting_participants (meeting_id, employee_id, response) VALUES
    (1, 2, 'pending'),
    (1, 3, 'accepted');
