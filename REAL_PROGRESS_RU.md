# Реальный прогресс проекта FLASH

Дата фиксации: 5 сентября 2026 года.

## Уже выполнено фактически

1. Создан публичный GitHub-репозиторий `olehworkfree-hash/flash-bounty-lab` и ветка `flash/evm-verification-2026-09-05`.
2. В ветку загружены Solidity-контракт `FlashLoanProbe`, 19 mock-тестов, отдельный Aave Arbitrum fork-тест, Foundry-конфигурация, devcontainer и безопасный installer с проверкой SHA-256.
3. Получен настоящий 3-из-3 RPC quorum для Arbitrum One на блоке 501964988. Три независимых endpoint вернули один и тот же block hash, parent hash, state root и transaction root.
4. На том же block hash через EIP-1898 `requireCanonical=true` три RPC одинаково подтвердили Aave flash-loan premium 5 bps, адреса двух USDC/WETH V2-пар, router/factory identity и decimals токенов.
5. Исторические Aave liquidation-транзакции найдены и raw signed bytes прочитаны только read-only. Мы их не подписывали и не отправляли.

## Что подготовлено к следующему запуску

- `scripts/anvil_fork_smoke.sh` запускает настоящий Anvil fork закреплённого Arbitrum-блока.
- На локальном chain id 31337 он проверяет bytecode Aave Pool и актуальную premium.
- Затем Foundry-тест запрашивает реальный `flashLoanSimple` внутри изолированного fork и доказывает атомарный repayment.
- `ci/verify.yml.template` готов для установки в `.github/workflows/verify.yml`.

## Единственный блокер GitHub Actions

Текущий fine-grained token имеет `Contents: write`, но не имеет разрешения `Workflows: write`. GitHub вернул HTTP 403 как для Contents API, так и для Git Data API при попытке создать `.github/workflows/verify.yml`.

Нужно открыть настройки токена `FLASH Make - bounty lab`, добавить repository permission **Workflows: Read and write**, после чего шаблон можно переместить в `.github/workflows/verify.yml` и CI запустится автоматически.

## Что не считается выполненным

- Fork-тест ещё не прошёл GitHub Actions.
- Контракт не развёрнут в Arbitrum mainnet.
- Пользовательские средства не переводились.
- Реальная транзакция от нашего кошелька не подписывалась и не отправлялась.
- Flash-loan repayment доказан кодом и готов к fork-запуску, но не объявляется завершённым до зелёного CI.
- Paper PnL не считается доходом.
