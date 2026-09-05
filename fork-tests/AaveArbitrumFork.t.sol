// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {FlashLoanProbe, IERC20Probe} from "../src/FlashLoanProbe.sol";
interface VmForkProbe { function deal(address, uint256) external; }
interface IWETHProbe is IERC20Probe { function deposit() external payable; }
interface IProviderProbe { function getPool() external view returns (address); }
interface IPremiumProbe { function FLASHLOAN_PREMIUM_TOTAL() external view returns (uint128); }
contract AaveArbitrumForkTest {
    VmForkProbe constant vm = VmForkProbe(address(uint160(uint256(keccak256("hevm cheat code")))));
    address constant PROVIDER = 0xa97684ead0e402dC232d5A977953DF7ECBaB3CDb;
    address constant POOL = 0x794a61358D6845594F94dc1DB02A252b5b4814aD;
    IWETHProbe constant WETH = IWETHProbe(0x82aF49447D8a07e3bd95BD0d56f35241523fBab1);
    event ForkRepaymentObserved(uint256 amount, uint256 premium, uint256 balanceAfter);
    function testActualAaveWethRepaymentOnIsolatedFork() public {
        require(block.chainid == 31337, "LOCAL_ANVIL_REQUIRED");
        require(IProviderProbe(PROVIDER).getPool() == POOL, "ADDRESS_BOOK_CHANGED");
        require(POOL.code.length > 0 && address(WETH).code.length > 0, "MISSING_FORK_CODE");
        vm.deal(address(this), 1 ether); // Simulation-only native currency, NOT income.
        WETH.deposit{value: 0.001 ether}();
        FlashLoanProbe receiver = new FlashLoanProbe(POOL);
        uint256 amount = 0.01 ether;
        uint256 cap = 0.0001 ether;
        uint256 expectedPremium = (amount * uint256(IPremiumProbe(POOL).FLASHLOAN_PREMIUM_TOTAL()) + 5000) / 10000;
        require(expectedPremium <= cap, "FEE_ABOVE_TEST_CAP");
        require(WETH.transfer(address(receiver), cap));
        receiver.probe(address(WETH), amount, cap);
        require(receiver.lastPremium() == expectedPremium, "UNEXPECTED_PREMIUM");
        require(WETH.balanceOf(address(receiver)) == cap - expectedPremium, "WRONG_FEE_BALANCE");
        emit ForkRepaymentObserved(amount, expectedPremium, WETH.balanceOf(address(receiver)));
    }
}
