// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * acer-kbd-rgb.c: Minimal 4-zone RGB keyboard backlight driver for
 * Acer Nitro/Predator laptops (tested: Nitro 5 AN515-45).
 *
 * Extracted from JafarAkhondali's acer-predator-turbo-and-rgb-keyboard
 * linux module (facer.c, GPL) so that ONLY the keyboard lighting code
 * runs, leaving the stock acer_wmi driver untouched. All WMI method IDs,
 * payload formats and the zone-enable init sequence are identical to
 * that community-tested driver.
 *
 * Interface (same as upstream, so facer_rgb.py works unchanged):
 *   /dev/acer-gkbbl-0        write 16 bytes: dynamic effect config
 *   /dev/acer-gkbbl-static-0 write 4 bytes:  {zone, red, green, blue}
 */

#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/acpi.h>
#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/wmi.h>

MODULE_DESCRIPTION("Minimal Acer 4-zone RGB keyboard backlight driver");
MODULE_LICENSE("GPL");
MODULE_AUTHOR("Extracted from JafarAkhondali's facer driver");

#define WMID_GUID4 "7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56"
MODULE_ALIAS("wmi:" WMID_GUID4);

/* WMI method IDs on WMID_GUID4 — identical to upstream facer.c */
#define ACER_WMID_SET_GAMING_LED_METHODID	 2
#define ACER_WMID_GET_GAMING_SYS_INFO_METHODID	 5
#define ACER_WMID_SET_GAMING_STATIC_LED_METHODID 6
#define ACER_WMID_SET_GAMINGKBBL_METHODID	20

#define GAMING_KBBL_CHR "acer-gkbbl"
#define GAMING_KBBL_CONFIG_LEN 16

#define GAMING_KBBL_STATIC_CHR "acer-gkbbl-static"
#define GAMING_KBBL_STATIC_CONFIG_LEN 4

static acpi_status
WMI_gaming_execute_u64(u32 method_id, u64 in, u64 *out)
{
	struct acpi_buffer input = { (acpi_size) sizeof(u64), (void *)(&in) };
	struct acpi_buffer result = { ACPI_ALLOCATE_BUFFER, NULL };
	union acpi_object *obj;
	u64 tmp = 0;
	acpi_status status;

	status = wmi_evaluate_method(WMID_GUID4, 0, method_id, &input, &result);

	if (ACPI_FAILURE(status))
		return status;
	obj = (union acpi_object *) result.pointer;

	if (obj) {
		if (obj->type == ACPI_TYPE_BUFFER) {
			if (obj->buffer.length == sizeof(u32))
				tmp = *((u32 *) obj->buffer.pointer);
			else if (obj->buffer.length == sizeof(u64))
				tmp = *((u64 *) obj->buffer.pointer);
		} else if (obj->type == ACPI_TYPE_INTEGER) {
			tmp = (u64) obj->integer.value;
		}
	}

	if (out)
		*out = tmp;

	kfree(result.pointer);

	return status;
}

static acpi_status
WMI_gaming_execute_u8_array(u32 method_id, u8 array[], size_t array_size)
{
	struct acpi_buffer input = { (acpi_size) array_size, (void *)(array) };
	struct acpi_buffer result = { ACPI_ALLOCATE_BUFFER, NULL };
	acpi_status status;

	status = wmi_evaluate_method(WMID_GUID4, 0, method_id, &input, &result);

	if (ACPI_FAILURE(status))
		return status;

	kfree(result.pointer);

	return status;
}

/* ---- dynamic effects device: /dev/acer-gkbbl-0 ---- */

static ssize_t gkbbl_drv_write(struct file *file,
		const char __user *buf, size_t count, loff_t *offset)
{
	u8 config_buf[GAMING_KBBL_CONFIG_LEN];

	if (count != GAMING_KBBL_CONFIG_LEN) {
		pr_err("acer-kbd-rgb: dynamic config must be %d bytes\n",
		       GAMING_KBBL_CONFIG_LEN);
		return -EINVAL;
	}
	if (copy_from_user(config_buf, buf, GAMING_KBBL_CONFIG_LEN))
		return -EFAULT;

	WMI_gaming_execute_u8_array(ACER_WMID_SET_GAMINGKBBL_METHODID,
				    config_buf, GAMING_KBBL_CONFIG_LEN);
	return count;
}

static const struct file_operations gkbbl_dev_fops = {
	.owner = THIS_MODULE,
	.write = gkbbl_drv_write,
};

/* ---- static per-zone color device: /dev/acer-gkbbl-static-0 ---- */

struct led_zone_set_param {
	u8 zone;
	u8 red;
	u8 green;
	u8 blue;
} __packed;

static ssize_t gkbbl_static_drv_write(struct file *file,
		const char __user *buf, size_t count, loff_t *offset)
{
	u8 config_buf[GAMING_KBBL_STATIC_CONFIG_LEN];
	struct led_zone_set_param set_params;
	struct acpi_buffer set_input;

	if (count != GAMING_KBBL_STATIC_CONFIG_LEN) {
		pr_err("acer-kbd-rgb: static config must be %d bytes\n",
		       GAMING_KBBL_STATIC_CONFIG_LEN);
		return -EINVAL;
	}
	if (copy_from_user(config_buf, buf, GAMING_KBBL_STATIC_CONFIG_LEN))
		return -EFAULT;

	set_params = (struct led_zone_set_param) {
		.zone = config_buf[0],
		.red = config_buf[1],
		.green = config_buf[2],
		.blue = config_buf[3],
	};
	set_input = (struct acpi_buffer) {
		sizeof(set_params),
		&set_params
	};

	wmi_evaluate_method(WMID_GUID4, 0,
			    ACER_WMID_SET_GAMING_STATIC_LED_METHODID,
			    &set_input, NULL);
	return count;
}

static const struct file_operations gkbbl_static_dev_fops = {
	.owner = THIS_MODULE,
	.write = gkbbl_static_drv_write,
};

/* ---- chardev plumbing ---- */

struct gkbbl_chardev {
	dev_t devt;
	struct cdev cdev;
	struct class *class;
	bool region, added, dev_created;
};

static struct gkbbl_chardev dyn_cdev, static_cdev;

static int gkbbl_dev_uevent(const struct device *dev,
			    struct kobj_uevent_env *env)
{
	/* world-writable: lighting only, same policy as upstream driver */
	add_uevent_var(env, "DEVMODE=%#o", 0666);
	return 0;
}

static void gkbbl_chardev_destroy(struct gkbbl_chardev *cd)
{
	if (cd->dev_created)
		device_destroy(cd->class, cd->devt);
	if (cd->class)
		class_destroy(cd->class);
	if (cd->added)
		cdev_del(&cd->cdev);
	if (cd->region)
		unregister_chrdev_region(cd->devt, 1);
	memset(cd, 0, sizeof(*cd));
}

static int gkbbl_chardev_create(struct gkbbl_chardev *cd, const char *name,
				const struct file_operations *fops)
{
	struct device *dev;
	int err;

	err = alloc_chrdev_region(&cd->devt, 0, 1, name);
	if (err < 0)
		return err;
	cd->region = true;

	cd->class = class_create(name);
	if (IS_ERR(cd->class)) {
		err = PTR_ERR(cd->class);
		cd->class = NULL;
		goto fail;
	}
	cd->class->dev_uevent = gkbbl_dev_uevent;

	cdev_init(&cd->cdev, fops);
	cd->cdev.owner = THIS_MODULE;
	err = cdev_add(&cd->cdev, cd->devt, 1);
	if (err)
		goto fail;
	cd->added = true;

	dev = device_create(cd->class, NULL, cd->devt, NULL, "%s-0", name);
	if (IS_ERR(dev)) {
		err = PTR_ERR(dev);
		goto fail;
	}
	cd->dev_created = true;

	return 0;
fail:
	gkbbl_chardev_destroy(cd);
	return err;
}

static int __init acer_kbd_rgb_init(void)
{
	u64 gaming_sysinfo;
	int err;

	if (!wmi_has_guid(WMID_GUID4)) {
		pr_err("acer-kbd-rgb: Acer gaming WMI interface not found\n");
		return -ENODEV;
	}

	/*
	 * Upstream: querying GetGamingSysInfo appears to be required to
	 * enable Nitro AN515-5x 4-zone LED keyboards, then turn on all
	 * 4 zones. Sequence identical to facer.c.
	 */
	WMI_gaming_execute_u64(ACER_WMID_GET_GAMING_SYS_INFO_METHODID, 0,
			       &gaming_sysinfo);
	WMI_gaming_execute_u64(ACER_WMID_SET_GAMING_LED_METHODID,
			       8L | (15UL << 40), NULL);

	err = gkbbl_chardev_create(&dyn_cdev, GAMING_KBBL_CHR,
				   &gkbbl_dev_fops);
	if (err)
		return err;

	err = gkbbl_chardev_create(&static_cdev, GAMING_KBBL_STATIC_CHR,
				   &gkbbl_static_dev_fops);
	if (err) {
		gkbbl_chardev_destroy(&dyn_cdev);
		return err;
	}

	pr_info("acer-kbd-rgb: 4-zone keyboard RGB devices ready\n");
	return 0;
}

static void __exit acer_kbd_rgb_exit(void)
{
	gkbbl_chardev_destroy(&static_cdev);
	gkbbl_chardev_destroy(&dyn_cdev);
}

module_init(acer_kbd_rgb_init);
module_exit(acer_kbd_rgb_exit);
