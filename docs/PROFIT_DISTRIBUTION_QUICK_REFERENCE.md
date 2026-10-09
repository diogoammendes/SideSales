# Referência Rápida - Distribuição de Lucros

## 🎯 Conceito Principal

**O sistema distribui apenas o LUCRO, não o valor total.**

```
Lucro Total = Total Recebido - Total Investido
Quota Justa = Investimento + Parte do Lucro
```

---

## 🔀 Dois Modos Disponíveis

### 1️⃣ PROPORCIONAL (Padrão)
```
Lucro do User = (Investimento User ÷ Total Investido) × Lucro Total
```

**Exemplo:** User investiu 60% → recebe 60% do lucro

### 2️⃣ IGUAL (50/50)
```
Lucro do User = Lucro Total ÷ Número de Users
```

**Exemplo:** 2 users → cada um recebe 50% do lucro (mesmo que tenham investido valores diferentes)

---

## 📊 Exemplo Numérico

| Item | Valor |
|------|-------|
| User A investiu | 600€ |
| User B investiu | 400€ |
| Total vendido | 1500€ |
| **Lucro Total** | **500€** |

### Modo PROPORCIONAL
- User A: 600€ + 300€ lucro = **900€** ✓
- User B: 400€ + 200€ lucro = **600€** ✓

### Modo IGUAL
- User A: 600€ + 250€ lucro = **850€** ✓
- User B: 400€ + 250€ lucro = **650€** ✓

---

## 💸 Acerto de Contas

**Se os pagamentos reais não correspondem à distribuição:**

| User | Recebeu | Devia Receber | Saldo |
|------|---------|---------------|-------|
| A | 900€ | 850€ | +50€ (paga) |
| B | 600€ | 650€ | -50€ (recebe) |

**Transferência:** A paga 50€ a B

---

## ✅ Interpretação dos Saldos

### 🔴 Saldo Positivo (+)
- Recebeu **mais** que a quota justa
- Deve **PAGAR** aos outros
- ⚠️ Não significa prejuízo!

### 🟢 Saldo Negativo (-)
- Recebeu **menos** que a quota justa
- Deve **RECEBER** dos outros
- ⚠️ Não significa mais lucro!

---

## 🛠️ Como Alterar o Modo

1. Vá para `/acerto/` (Acerto de Contas)
2. Use o dropdown no topo (só admin)
3. Alteração aplica-se imediatamente

---

## ❓ FAQ Rápido

**Q: Posso perder o investimento?**
R: Não. Você sempre recebe no mínimo o seu investimento de volta.

**Q: Por que quem tem mais lucro paga?**
R: No modo IGUAL, para equalizar o lucro de todos.

**Q: Vendas em rascunho contam?**
R: Não. Só vendas CONFIRMED ou SETTLED.

---

## 📚 Documentação Completa

Ver: `docs/profit-distribution-guide.md`
