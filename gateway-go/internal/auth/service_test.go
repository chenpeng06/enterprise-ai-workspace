package auth

import "testing"

func TestPermissionMatrix(t *testing.T) {
	if !HasPermission(&Identity{Role: "owner", Permissions: PermissionsForRole("owner")}, PermissionQuota) {
		t.Fatal("owner 应该拥有配额权限")
	}
	admin := &Identity{Role: "admin", Permissions: PermissionsForRole("admin")}
	if !HasPermission(admin, PermissionDocsWrite) {
		t.Fatal("admin 应该可以上传文档")
	}
	if HasPermission(admin, PermissionQuota) {
		t.Fatal("admin 不应拥有配额权限")
	}
	if HasPermission(admin, PermissionAdmins) {
		t.Fatal("admin 不应拥有管理员任命权限")
	}
	viewer := &Identity{Role: "viewer", Permissions: PermissionsForRole("viewer")}
	if !HasPermission(viewer, PermissionChatUse) {
		t.Fatal("viewer 应该可以使用对话")
	}
	if HasPermission(viewer, PermissionDocsWrite) || HasPermission(viewer, PermissionUsersRead) {
		t.Fatal("viewer 不应拥有写或用户管理权限")
	}
}

func TestRoleManagementBounds(t *testing.T) {
	if CanManageRole("admin", "admin") || CanManageRole("admin", "owner") {
		t.Fatal("受控管理员不能创建管理员或超管")
	}
	if !CanManageRole("admin", "editor") || !CanManageRole("admin", "viewer") {
		t.Fatal("受控管理员应能创建运营/游客")
	}
	if !CanManageRole("owner", "admin") || !CanManageRole("owner", "viewer") {
		t.Fatal("超管应能创建受控管理员/游客")
	}
	if CanTouchRole("admin", "owner") || CanTouchRole("admin", "admin") {
		t.Fatal("受控管理员不能操作用户管理员/超管")
	}
	if !CanTouchRole("owner", "admin") {
		t.Fatal("超管应能操作受控管理员")
	}
}

func TestPasswordHashAndValidation(t *testing.T) {
	if err := ValidatePassword("short"); err == nil {
		t.Fatal("短密码必须被拒绝")
	}
	hash, err := HashPassword("Admin@12345")
	if err != nil {
		t.Fatalf("密码哈希失败: %v", err)
	}
	if hash == "Admin@12345" || len(hash) < 20 {
		t.Fatal("密码必须 bcrypt 哈希存储")
	}
}
