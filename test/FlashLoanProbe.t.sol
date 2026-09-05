// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {FlashLoanProbe, IERC20Probe} from "../src/FlashLoanProbe.sol";
interface VmProbe {
    function chainId(uint256) external;
    function prank(address) external;
    function expectRevert() external;
}
contract MockToken is IERC20Probe {
    mapping(address => uint256) public override balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    bool public rejectApproval;
    function mint(address who, uint256 value) external { balanceOf[who] += value; }
    function reject(bool flag) external { rejectApproval = flag; }
    function approve(address spender, uint256 value) external override returns (bool) {
        if (rejectApproval) return false;
        allowance[msg.sender][spender] = value; return true;
    }
    function transfer(address to, uint256 value) external override returns (bool) {
        balanceOf[msg.sender] -= value; balanceOf[to] += value; return true;
    }
    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        allowance[from][msg.sender] -= value;
        balanceOf[from] -= value; balanceOf[to] += value; return true;
    }
}
contract MockPool {
    uint256 public fee = 5;
    uint256 public mode;
    function configure(uint256 newFee, uint256 newMode) external { fee = newFee; mode = newMode; }
    function flashLoanSimple(address receiver, address asset, uint256 amount, bytes calldata params, uint16) external {
        if (mode == 5) return;
        MockToken token = MockToken(asset);
        token.transfer(receiver, amount);
        address initiator = mode == 1 ? address(7) : msg.sender;
        bytes memory payload = mode == 2 ? bytes("altered") : params;
        uint256 callbackAmount = mode == 3 ? amount + 1 : amount;
        require(FlashLoanProbe(receiver).executeOperation(asset, callbackAmount, fee, initiator, payload));
        if (mode == 4) FlashLoanProbe(receiver).executeOperation(asset, amount, fee, initiator, payload);
        if (mode != 6) token.transferFrom(receiver, address(this), amount + fee);
    }
}
contract FlashLoanProbeTest {
    VmProbe constant vm = VmProbe(address(uint160(uint256(keccak256("hevm cheat code")))));
    MockToken token;
    MockPool pool;
    FlashLoanProbe probe;
    function setUp() public {
        vm.chainId(31337);
        token = new MockToken(); pool = new MockPool(); probe = new FlashLoanProbe(address(pool));
        token.mint(address(pool), 1000000); token.mint(address(probe), 100);
    }
    function testRepaymentAndAllowanceCleared() public {
        probe.probe(address(token), 10000, 5);
        require(token.balanceOf(address(probe)) == 95);
        require(token.balanceOf(address(pool)) == 1000005);
        require(token.allowance(address(probe), address(pool)) == 0);
        require(probe.lastPremium() == 5);
    }
    function testRepeatedLoans() public {
        probe.probe(address(token), 1000, 5); probe.probe(address(token), 2000, 5);
        require(probe.nonce() == 2 && token.balanceOf(address(probe)) == 90);
    }
    function testRejectExternalCallback() public { vm.expectRevert(); probe.executeOperation(address(token), 100, 5, address(probe), ""); }
    function testRejectNonOwner() public { vm.prank(address(9)); vm.expectRevert(); probe.probe(address(token), 100, 5); }
    function testRejectPremium() public { pool.configure(6, 0); vm.expectRevert(); probe.probe(address(token), 100, 5); }
    function testRejectInitiator() public { pool.configure(5, 1); vm.expectRevert(); probe.probe(address(token), 100, 5); }
    function testRejectParams() public { pool.configure(5, 2); vm.expectRevert(); probe.probe(address(token), 100, 5); }
    function testRejectAmount() public { pool.configure(5, 3); vm.expectRevert(); probe.probe(address(token), 100, 5); }
    function testRejectDoubleCallback() public { pool.configure(5, 4); vm.expectRevert(); probe.probe(address(token), 100, 5); }
    function testRejectMissingCallback() public { pool.configure(5, 5); vm.expectRevert(); probe.probe(address(token), 100, 5); }
    function testRejectNoRepayment() public { pool.configure(5, 6); vm.expectRevert(); probe.probe(address(token), 100, 5); }
    function testRejectFalseApprove() public { token.reject(true); vm.expectRevert(); probe.probe(address(token), 100, 5); }
    function testRejectMissingPrefund() public { vm.expectRevert(); probe.probe(address(token), 100, 101); }
    function testRejectZeroAmount() public { vm.expectRevert(); probe.probe(address(token), 0, 5); }
    function testRejectMainnetDeploy() public { vm.chainId(42161); vm.expectRevert(); new FlashLoanProbe(address(pool)); }
    function testRejectChainChanged() public { vm.chainId(42161); vm.expectRevert(); probe.probe(address(token), 100, 5); }
    function testRejectEmptyPool() public { vm.expectRevert(); new FlashLoanProbe(address(123)); }
    function testOwnerRescue() public { probe.rescue(address(token), 10); require(token.balanceOf(address(this)) == 10); }
    function testRejectNonOwnerRescue() public { vm.prank(address(9)); vm.expectRevert(); probe.rescue(address(token), 10); }
}
