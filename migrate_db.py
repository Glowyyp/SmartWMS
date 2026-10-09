import sqlite3

conn = sqlite3.connect('ecommerce/backend/ecommerce.db')
c = conn.cursor()

# Verificar colunas existentes
c.execute('PRAGMA table_info(product_inventory)')
cols = [row[1] for row in c.fetchall()]
print('Colunas existentes:', cols)

if 'warehouse_location' not in cols:
    c.execute('ALTER TABLE product_inventory ADD COLUMN warehouse_location VARCHAR(50)')
    print('Coluna warehouse_location adicionada com sucesso!')
    
    # Atribuir zonas padrao para produtos existentes
    c.execute("UPDATE product_inventory SET warehouse_location = 'A' WHERE sku LIKE 'SKU-004%'")
    c.execute("UPDATE product_inventory SET warehouse_location = 'B' WHERE sku LIKE 'SKU-005%' OR sku LIKE 'SKU-006%'")
    c.execute("UPDATE product_inventory SET warehouse_location = 'C' WHERE sku LIKE 'SKU-001%' OR sku LIKE 'SKU-002%' OR sku LIKE 'SKU-003%'")
    print('Zonas padrao atribuidas.')
    conn.commit()
else:
    print('Coluna warehouse_location ja existe.')

# Mostrar produtos com suas localizacoes
c.execute('SELECT sku, product_name, warehouse_location FROM product_inventory LIMIT 20')
rows = c.fetchall()
print('Produtos com localizacao:')
for row in rows:
    print(f'  {row[0]} | {row[1][:30]} | Zona: {row[2]}')

conn.close()
