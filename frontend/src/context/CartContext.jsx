import { createContext, useContext, useEffect, useState, useCallback } from 'react';

const CartContext = createContext(null);
const KEY = 'minishop_cart';

const read = () => {
  try { return JSON.parse(localStorage.getItem(KEY)) || []; } catch { return []; }
};

export function CartProvider({ children }) {
  const [items, setItems] = useState(read); // [{product_id,name,price,quantity,stock}]

  useEffect(() => {
    try { localStorage.setItem(KEY, JSON.stringify(items)); } catch { /* ignore */ }
  }, [items]);

  const add = useCallback((product, qty = 1) => {
    setItems((cur) => {
      const found = cur.find((i) => i.product_id === product.id);
      if (found) {
        return cur.map((i) => i.product_id === product.id
          ? { ...i, quantity: i.quantity + qty, price: product.price, stock: product.stock_quantity } : i);
      }
      return [...cur, { product_id: product.id, name: product.name, price: product.price, quantity: qty, stock: product.stock_quantity }];
    });
  }, []);

  const setQty = useCallback((id, quantity) => {
    setItems((cur) => cur.map((i) => (i.product_id === id ? { ...i, quantity: Math.max(1, quantity) } : i)));
  }, []);

  const remove = useCallback((id) => setItems((cur) => cur.filter((i) => i.product_id !== id)), []);
  const clear = useCallback(() => setItems([]), []);

  const total = items.reduce((s, i) => s + i.price * i.quantity, 0);
  const count = items.reduce((s, i) => s + i.quantity, 0);

  return (
    <CartContext.Provider value={{ items, add, setQty, remove, clear, total, count }}>
      {children}
    </CartContext.Provider>
  );
}

export const useCart = () => useContext(CartContext);
