# Guia de Distribuição de Lucros

## Visão Geral

O sistema SideSales oferece dois modos configuráveis para distribuir o lucro total das vendas entre os utilizadores.

**Conceito Fundamental:** O sistema distribui apenas o **lucro** (receita - investimento), não o valor total recebido. Cada utilizador sempre recupera o seu investimento inicial primeiro.

## Fórmula Base

```
Lucro Total = Total Recebido das Vendas - Total Investido
```

Cada utilizador recebe:
```
Quota Justa = Investimento do Utilizador + Parte do Lucro
```

## Modos de Distribuição

### 1. Modo Proporcional (Padrão)

**Conceito:** O lucro é distribuído proporcionalmente ao investimento de cada utilizador.

**Fórmula:**
```
Parte do Lucro = (Investimento do Utilizador ÷ Total Investido) × Lucro Total
```

**Exemplo:**

| Utilizador | Investimento | % Investimento | Lucro Atribuído | Total a Receber |
|------------|--------------|----------------|-----------------|-----------------|
| João       | 600€         | 60%            | 300€            | 900€            |
| Maria      | 400€         | 40%            | 200€            | 600€            |
| **Total**  | **1000€**    | **100%**       | **500€**        | **1500€**       |

**Resultado:**
- João tem lucro de +300€ (50% do investimento dele)
- Maria tem lucro de +200€ (50% do investimento dela)
- Quem investiu mais ganha mais lucro em termos absolutos

---

### 2. Modo Lucro Igual (50/50)

**Conceito:** Cada utilizador recupera o seu investimento e recebe uma parte **igual** do lucro total.

**Fórmula:**
```
Parte do Lucro = Lucro Total ÷ Número de Utilizadores
```

**Exemplo (mesmo cenário):**

| Utilizador | Investimento | Lucro Atribuído | Total a Receber | Lucro Real |
|------------|--------------|-----------------|-----------------|------------|
| João       | 600€         | 250€            | 850€            | +250€      |
| Maria      | 400€         | 250€            | 650€            | +250€      |
| **Total**  | **1000€**    | **500€**        | **1500€**       | **+500€**  |

**Resultado:**
- João tem lucro de +250€ (41.67% do investimento dele)
- Maria tem lucro de +250€ (62.5% do investimento dela)
- Ambos têm o **mesmo lucro** em termos absolutos
- Maria tem melhor retorno percentual porque investiu menos

---

## Acerto de Contas

Quando os pagamentos reais não correspondem à distribuição configurada, o sistema calcula as transferências necessárias.

### Exemplo Prático - Modo Igual

**Situação Real:**
- João recebeu 900€ dos clientes
- Maria recebeu 600€ dos clientes

**Situação Justa (Modo Igual):**
- João devia receber 850€ (600€ + 250€ lucro)
- Maria devia receber 650€ (400€ + 250€ lucro)

**Cálculo do Acerto:**

| Utilizador | Investiu | Recebeu | Devia Receber | Saldo    | Ação                |
|------------|----------|---------|---------------|----------|---------------------|
| João       | 600€     | 900€    | 850€          | **+50€** | 🔴 Deve pagar 50€   |
| Maria      | 400€     | 600€    | 650€          | **-50€** | 🟢 Deve receber 50€ |

**Transferência:** João paga 50€ a Maria

**Resultado Final após Transferência:**
- João: 900€ - 50€ = 850€ → Lucro de +250€ ✓
- Maria: 600€ + 50€ = 650€ → Lucro de +250€ ✓

---

## Interpretação dos Saldos

### Saldo Positivo (Vermelho)
```
Saldo = Recebeu - Devia Receber > 0
```
- Significa que o utilizador recebeu **mais** do que a sua quota justa
- Este utilizador deve **pagar** aos outros para equilibrar
- **Isto não significa que teve prejuízo!** Apenas que recebeu mais do que o acordado

### Saldo Negativo (Verde)
```
Saldo = Recebeu - Devia Receber < 0
```
- Significa que o utilizador recebeu **menos** do que a sua quota justa
- Este utilizador deve **receber** dos outros para equilibrar
- **Isto não significa que teve mais lucro!** Apenas que ainda não recebeu tudo

### Exemplo para Clarificar

No exemplo do modo igual acima:
- **João** tem saldo +50€ (recebeu 900€, devia 850€)
  - Lucro atual: +300€ (900€ - 600€)
  - Deve pagar 50€ porque recebeu mais do que a quota justa
  - Após pagar: lucro de +250€
  
- **Maria** tem saldo -50€ (recebeu 600€, devia 650€)
  - Lucro atual: +200€ (600€ - 400€)
  - Deve receber 50€ porque recebeu menos do que a quota justa
  - Após receber: lucro de +250€

**Conclusão:** Quem tem mais lucro atual pode ter que pagar para equalizar conforme o modo de distribuição configurado.

---

## Como Alterar o Modo

1. Aceda a **Acerto de Contas** (`/acerto/`)
2. No topo da página, verá o modo atual
3. Se for **Administrador**, pode alterar no dropdown
4. A alteração aplica-se imediatamente a todos os cálculos

**Nota:** Apenas utilizadores com privilégios de administrador (role ADMIN ou superuser) podem alterar o modo de distribuição.

---

## Perguntas Frequentes

### Q: Posso perder o meu investimento?
**R:** Não. O sistema sempre calcula que cada utilizador deve receber no mínimo o seu investimento de volta. A distribuição afeta apenas o lucro.

### Q: O que acontece se houver prejuízo (vendas < investimento)?
**R:** O prejuízo é distribuído da mesma forma que o lucro. No modo proporcional, quem investiu mais assume mais prejuízo. No modo igual, o prejuízo é dividido igualmente.

### Q: Posso ter diferentes modos para diferentes compras?
**R:** Não. O modo de distribuição é uma configuração global que se aplica a todas as compras e vendas do sistema.

### Q: Como funcionam as vendas em rascunho?
**R:** Vendas com status DRAFT são excluídas de todos os cálculos de lucro e acerto de contas. Apenas vendas CONFIRMED ou SETTLED são contabilizadas.

### Q: O que significa a coluna "Resultado"?
**R:** Resultado = Recebido - Investido. Mostra o lucro (ou prejuízo) líquido de cada utilizador antes do acerto.

---

## Implementação Técnica

### Migração de Base de Dados

```bash
python manage.py migrate
```

A migração `0005_add_system_settings` cria a tabela `SystemSettings` com o modo padrão PROPORTIONAL.

### Modelos

- **SystemSettings**: Singleton que armazena o `distribution_mode`
- Choices: `PROPORTIONAL` ou `EQUAL`

### Endpoints

- `GET /acerto/` - Vista de acerto de contas com modo de distribuição
- `POST /configuracoes/distribuicao/` - Alterar modo (admin apenas)

### Testes

Execute os testes de distribuição:
```bash
python manage.py test operations.tests.DistributionModeTests
```

Os testes cobrem:
- Distribuição proporcional no ledger e settlement
- Distribuição igual no ledger e settlement
- Cálculo correto de transferências
- Validação de saldos positivos/negativos
