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

CREATE TABLE contacts (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	channel VARCHAR(12) NOT NULL, 
	handle VARCHAR(80) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	unread INTEGER NOT NULL, 
	opted_out BOOLEAN NOT NULL, 
	last_message_at TIMESTAMP WITH TIME ZONE, 
	last_inbound_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_contacts_store_channel_handle UNIQUE (store_id, channel, handle), 
	CONSTRAINT ck_contacts_channel CHECK (channel IN ('whatsapp', 'messenger', 'instagram')), 
	FOREIGN KEY(store_id) REFERENCES stores (id) ON DELETE CASCADE
);

CREATE INDEX ix_contacts_store_last ON contacts (store_id, last_message_at);

CREATE INDEX ix_contacts_store_id ON contacts (store_id);

CREATE TABLE products (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	sku VARCHAR(60) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	description TEXT NOT NULL, 
	price_dzd INTEGER NOT NULL, 
	cost_dzd INTEGER NOT NULL, 
	stock INTEGER NOT NULL, 
	track_stock BOOLEAN NOT NULL, 
	low_stock INTEGER NOT NULL, 
	delivery_fee_dzd INTEGER NOT NULL, 
	upsell_product_id VARCHAR(36), 
	upsell_price_dzd INTEGER NOT NULL, 
	form_enabled BOOLEAN NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_products_store_sku UNIQUE (store_id, sku), 
	CONSTRAINT ck_products_money CHECK (price_dzd >= 0 AND cost_dzd >= 0), 
	FOREIGN KEY(store_id) REFERENCES stores (id) ON DELETE CASCADE, 
	FOREIGN KEY(upsell_product_id) REFERENCES products (id) ON DELETE SET NULL
);

CREATE INDEX ix_products_store_id ON products (store_id);

CREATE TABLE rules (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	event VARCHAR(20) NOT NULL, 
	conditions JSON NOT NULL, 
	actions JSON NOT NULL, 
	active BOOLEAN NOT NULL, 
	runs INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_rules_event CHECK (event IN ('order_created', 'stage_changed')), 
	FOREIGN KEY(store_id) REFERENCES stores (id) ON DELETE CASCADE
);

CREATE INDEX ix_rules_store_id ON rules (store_id);

CREATE TABLE users (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	role VARCHAR(10) NOT NULL, 
	active BOOLEAN NOT NULL, 
	prefs JSON NOT NULL, 
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

CREATE TABLE campaigns (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	text TEXT NOT NULL, 
	audience JSON NOT NULL, 
	recipients JSON NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	created_by_id VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(store_id) REFERENCES stores (id) ON DELETE CASCADE, 
	FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_campaigns_store_id ON campaigns (store_id);

CREATE TABLE payouts (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	carrier VARCHAR(30) NOT NULL, 
	reference VARCHAR(120) NOT NULL, 
	filename VARCHAR(200) NOT NULL, 
	rows INTEGER NOT NULL, 
	matched INTEGER NOT NULL, 
	collected_dzd INTEGER NOT NULL, 
	fees_dzd INTEGER NOT NULL, 
	issues JSON NOT NULL, 
	created_by_id VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(store_id) REFERENCES stores (id) ON DELETE CASCADE, 
	FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_payouts_store_id ON payouts (store_id);

CREATE TABLE saved_views (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	name VARCHAR(60) NOT NULL, 
	query VARCHAR(300) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(store_id) REFERENCES stores (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_saved_views_user_id ON saved_views (user_id);

CREATE INDEX ix_saved_views_store_id ON saved_views (store_id);

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
	tags JSON NOT NULL, 
	stock_applied BOOLEAN NOT NULL, 
	paid_at TIMESTAMP WITH TIME ZONE, 
	cod_collected_dzd INTEGER, 
	carrier_fee_dzd INTEGER, 
	payout_id VARCHAR(36), 
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
	FOREIGN KEY(payout_id) REFERENCES payouts (id) ON DELETE SET NULL, 
	FOREIGN KEY(assigned_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	FOREIGN KEY(confirmed_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_orders_store_phone ON orders (store_id, phone);

CREATE INDEX ix_orders_store_stage_created ON orders (store_id, stage, created_at);

CREATE INDEX ix_orders_store_wilaya ON orders (store_id, wilaya_code);

CREATE INDEX ix_orders_store_id ON orders (store_id);

CREATE TABLE carts (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	product_id VARCHAR(36), 
	token VARCHAR(48) NOT NULL, 
	customer_name VARCHAR(120) NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	data JSON NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	otp_hash VARCHAR(128) NOT NULL, 
	otp_expires_at TIMESTAMP WITH TIME ZONE, 
	otp_tries INTEGER NOT NULL, 
	otp_sends INTEGER NOT NULL, 
	recovery_sent_at TIMESTAMP WITH TIME ZONE, 
	order_id VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(store_id) REFERENCES stores (id) ON DELETE CASCADE, 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE SET NULL, 
	UNIQUE (token), 
	FOREIGN KEY(order_id) REFERENCES orders (id) ON DELETE SET NULL
);

CREATE INDEX ix_carts_store_status ON carts (store_id, status, updated_at);

CREATE INDEX ix_carts_store_id ON carts (store_id);

CREATE TABLE messages (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	order_id VARCHAR(36), 
	contact_id VARCHAR(36), 
	kind VARCHAR(20) NOT NULL, 
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
	FOREIGN KEY(order_id) REFERENCES orders (id) ON DELETE CASCADE, 
	FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE CASCADE
);

CREATE INDEX ix_messages_order_id ON messages (order_id);

CREATE INDEX ix_messages_store_id ON messages (store_id);

CREATE INDEX ix_messages_contact_id ON messages (contact_id);

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

CREATE INDEX ix_events_store_created ON order_events (store_id, created_at);

CREATE INDEX ix_order_events_store_id ON order_events (store_id);

CREATE INDEX ix_order_events_order_id ON order_events (order_id);

CREATE TABLE stock_moves (
	id VARCHAR(36) NOT NULL, 
	store_id VARCHAR(36) NOT NULL, 
	product_id VARCHAR(36) NOT NULL, 
	order_id VARCHAR(36), 
	delta INTEGER NOT NULL, 
	reason VARCHAR(30) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(store_id) REFERENCES stores (id) ON DELETE CASCADE, 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE, 
	FOREIGN KEY(order_id) REFERENCES orders (id) ON DELETE SET NULL
);

CREATE INDEX ix_stock_moves_product_id ON stock_moves (product_id);

CREATE INDEX ix_stock_moves_store_id ON stock_moves (store_id);
