-- Generated from app/models.py (PostgreSQL). The app creates these tables on start.

CREATE TABLE stores (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	api_key VARCHAR(64) NOT NULL, 
	plan VARCHAR(20) NOT NULL, 
	settings JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (api_key)
);

CREATE TABLE users (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	role VARCHAR(10) NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_users_role CHECK (role IN ('owner', 'agent')), 
	FOREIGN KEY(store_id) REFERENCES stores (id) ON DELETE CASCADE
);

CREATE INDEX ix_users_store_id ON users (store_id);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE blacklist (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	reason VARCHAR(200) NOT NULL, 
	created_by_id VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_blacklist_store_phone UNIQUE (store_id, phone), 
	FOREIGN KEY(store_id) REFERENCES stores (id) ON DELETE CASCADE, 
	FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_blacklist_store_id ON blacklist (store_id);

CREATE TABLE orders (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	external_id VARCHAR(80), 
	source VARCHAR(20) NOT NULL, 
	customer_name VARCHAR(120) NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	phone_valid BOOLEAN NOT NULL, 
	wilaya_code INTEGER, 
	commune VARCHAR(120) NOT NULL, 
	address VARCHAR(255) NOT NULL, 
	delivery_type VARCHAR(10) NOT NULL, 
	items JSON NOT NULL, 
	total_dzd INTEGER NOT NULL, 
	delivery_fee_dzd INTEGER NOT NULL, 
	note TEXT NOT NULL, 
	stage VARCHAR(12) NOT NULL, 
	cancel_reason VARCHAR(60) NOT NULL, 
	preferred_slot VARCHAR(12) NOT NULL, 
	attempts INTEGER NOT NULL, 
	risk_score INTEGER NOT NULL, 
	risk_reasons JSON NOT NULL, 
	carrier VARCHAR(30) NOT NULL, 
	tracking VARCHAR(60) NOT NULL, 
	assigned_user_id VARCHAR(36), 
	confirmed_by_id VARCHAR(36), 
	last_contact_at TIMESTAMP WITH TIME ZONE, 
	postponed_until TIMESTAMP WITH TIME ZONE, 
	confirmed_at TIMESTAMP WITH TIME ZONE, 
	shipped_at TIMESTAMP WITH TIME ZONE, 
	closed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_orders_store_external UNIQUE (store_id, external_id), 
	CONSTRAINT ck_orders_stage CHECK (stage IN ('new', 'pending', 'confirmed', 'postponed', 'no_answer', 'cancelled', 'shipped', 'delivered', 'returned')), 
	CONSTRAINT ck_orders_delivery_type CHECK (delivery_type IN ('home', 'stopdesk')), 
	CONSTRAINT ck_orders_total CHECK (total_dzd >= 0), 
	FOREIGN KEY(store_id) REFERENCES stores (id) ON DELETE CASCADE, 
	FOREIGN KEY(assigned_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	FOREIGN KEY(confirmed_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_orders_store_stage_created ON orders (store_id, stage, created_at);

CREATE INDEX ix_orders_store_wilaya ON orders (store_id, wilaya_code);

CREATE INDEX ix_orders_store_id ON orders (store_id);

CREATE INDEX ix_orders_store_phone ON orders (store_id, phone);

CREATE TABLE messages (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	order_id VARCHAR(36) NOT NULL, 
	direction VARCHAR(3) NOT NULL, 
	channel VARCHAR(20) NOT NULL, 
	text TEXT NOT NULL, 
	intent VARCHAR(20) NOT NULL, 
	ai BOOLEAN NOT NULL, 
	provider_id VARCHAR(120), 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_messages_direction CHECK (direction IN ('in', 'out')), 
	CONSTRAINT uq_messages_provider UNIQUE (store_id, provider_id), 
	FOREIGN KEY(store_id) REFERENCES stores (id) ON DELETE CASCADE, 
	FOREIGN KEY(order_id) REFERENCES orders (id) ON DELETE CASCADE
);

CREATE INDEX ix_messages_order_id ON messages (order_id);

CREATE INDEX ix_messages_store_id ON messages (store_id);

CREATE TABLE order_events (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	order_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36), 
	kind VARCHAR(20) NOT NULL, 
	text TEXT NOT NULL, 
	data JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(store_id) REFERENCES stores (id) ON DELETE CASCADE, 
	FOREIGN KEY(order_id) REFERENCES orders (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_order_events_store_id ON order_events (store_id);

CREATE INDEX ix_order_events_order_id ON order_events (order_id);

CREATE INDEX ix_events_store_created ON order_events (store_id, created_at);
