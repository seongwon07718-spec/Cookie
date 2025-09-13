import aiosqlite

async def init_db():
    db = await aiosqlite.connect('ticket.db')
    await db.execute('''
    CREATE TABLE IF NOT EXISTS settings(
        guild_id TEXT PRIMARY KEY,
        manager_role_id TEXT,
        category_id TEXT,
        log_channel_id TEXT
    )''')
    await db.execute('''
    CREATE TABLE IF NOT EXISTS open_tickets(
        guild_id TEXT,
        user_id TEXT,
        channel_id TEXT,
        PRIMARY KEY (guild_id, user_id)
    )''')
    await db.commit()
    return db

async def get_settings(db, guild_id):
    cur = await db.execute(
        'SELECT manager_role_id, category_id, log_channel_id FROM settings WHERE guild_id=?',
        (str(guild_id),)
    )
    row = await cur.fetchone()
    return row

async def upsert_settings(db, guild_id, manager_role_id, category_id, log_channel_id):
    await db.execute('''
    INSERT INTO settings(guild_id, manager_role_id, category_id, log_channel_id)
    VALUES(?,?,?,?)
    ON CONFLICT(guild_id) DO UPDATE SET
        manager_role_id=excluded.manager_role_id,
        category_id=excluded.category_id,
        log_channel_id=excluded.log_channel_id
    ''', (str(guild_id), manager_role_id, category_id, log_channel_id))
    await db.commit()

async def get_open_ticket(db, guild_id, user_id):
    cur = await db.execute(
        'SELECT channel_id FROM open_tickets WHERE guild_id=? AND user_id=?',
        (str(guild_id), str(user_id))
    )
    row = await cur.fetchone()
    return row[0] if row else None

async def add_open_ticket(db, guild_id, user_id, channel_id):
    await db.execute(
        'INSERT OR REPLACE INTO open_tickets(guild_id, user_id, channel_id) VALUES(?,?,?)',
        (str(guild_id), str(user_id), str(channel_id))
    )
    await db.commit()

async def remove_open_ticket(db, guild_id, user_id):
    await db.execute(
        'DELETE FROM open_tickets WHERE guild_id=? AND user_id=?',
        (str(guild_id), str(user_id))
    )
    await db.commit()
