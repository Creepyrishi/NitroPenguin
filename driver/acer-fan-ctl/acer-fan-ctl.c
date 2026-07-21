// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * acer-fan-ctl.c: Minimal fan control driver for Acer Nitro/Predator
 * laptops (tested: Nitro 5 AN515-45).
 *
 * Fan-control WMI sequences extracted verbatim from the community
 * Linuwu-Sense driver (0x7375646F/Linuwu-Sense, GPL): behavior
 * constants for auto/max/custom and the fan-speed encoding are
 * identical to that community-tested implementation. Only the fan
 * code runs here — the stock acer_wmi driver stays untouched.
 *
 * Interface:
 *   /sys/bus/wmi/drivers/acer-fan-ctl/fan_speed
 *     write "cpu,gpu" percentages (0-100). 0 = automatic for that fan.
 *       "0,0"     -> full auto (firmware curve, boot default)
 *       "100,100" -> max fans
 *       "55,40"   -> custom duty per fan
 *     read  -> last written values ("0,0" after load: module never
 *              changes fan state by itself).
 *
 * The module performs no WMI calls at load/unload. Firmware thermal
 * protection remains active in every mode.
 */

#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/acpi.h>
#include <linux/wmi.h>

MODULE_DESCRIPTION("Minimal Acer gaming fan control driver");
MODULE_LICENSE("GPL");
MODULE_AUTHOR("Extracted from Linuwu-Sense");

#define WMID_GUID4 "7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56"
MODULE_ALIAS("wmi:" WMID_GUID4);

#define ACER_WMID_SET_GAMING_FAN_BEHAVIOR_METHODID 14
#define ACER_WMID_SET_GAMING_FAN_SPEED_METHODID    16

/* Behavior words, identical to Linuwu-Sense acer_set_fan_speed() */
#define FAN_BEHAVIOR_AUTO	0x410009
#define FAN_BEHAVIOR_MAX	0x820009
#define FAN_BEHAVIOR_CUSTOM	0xC30009
#define FAN_BEHAVIOR_GPU_ONLY_A	0x10001
#define FAN_BEHAVIOR_GPU_ONLY_B	0xC00008
#define FAN_BEHAVIOR_CPU_ONLY_A	0x400008
#define FAN_BEHAVIOR_CPU_ONLY_B	0x30001

#define FAN_INDEX_CPU 1
#define FAN_INDEX_GPU 4

static int cpu_fan_speed;
static int gpu_fan_speed;
static DEFINE_MUTEX(fan_lock);

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

/* Identical to Linuwu-Sense fan_val_calc() */
static u64 fan_val_calc(int percentage, int fan_index)
{
	return (((percentage * 25600) / 100) & 0xFF00) + fan_index;
}

#define FAN_CALL(method, value)						\
	do {								\
		acpi_status s_ = WMI_gaming_execute_u64((method),	\
							(value), NULL);	\
		if (ACPI_FAILURE(s_)) {					\
			pr_err("acer-fan-ctl: WMI call failed\n");	\
			return -EIO;					\
		}							\
	} while (0)

/* Same decision tree as Linuwu-Sense acer_set_fan_speed() */
static int set_fan_speed(int cpu, int gpu)
{
	if (cpu == 100 && gpu == 100) {
		FAN_CALL(ACER_WMID_SET_GAMING_FAN_BEHAVIOR_METHODID,
			 FAN_BEHAVIOR_MAX);
	} else if (cpu == 0 && gpu == 0) {
		FAN_CALL(ACER_WMID_SET_GAMING_FAN_BEHAVIOR_METHODID,
			 FAN_BEHAVIOR_AUTO);
	} else if (cpu == 0) {
		FAN_CALL(ACER_WMID_SET_GAMING_FAN_BEHAVIOR_METHODID,
			 FAN_BEHAVIOR_GPU_ONLY_A);
		FAN_CALL(ACER_WMID_SET_GAMING_FAN_BEHAVIOR_METHODID,
			 FAN_BEHAVIOR_GPU_ONLY_B);
		FAN_CALL(ACER_WMID_SET_GAMING_FAN_SPEED_METHODID,
			 fan_val_calc(gpu, FAN_INDEX_GPU));
	} else if (gpu == 0) {
		FAN_CALL(ACER_WMID_SET_GAMING_FAN_BEHAVIOR_METHODID,
			 FAN_BEHAVIOR_CPU_ONLY_A);
		FAN_CALL(ACER_WMID_SET_GAMING_FAN_BEHAVIOR_METHODID,
			 FAN_BEHAVIOR_CPU_ONLY_B);
		FAN_CALL(ACER_WMID_SET_GAMING_FAN_SPEED_METHODID,
			 fan_val_calc(cpu, FAN_INDEX_CPU));
	} else {
		FAN_CALL(ACER_WMID_SET_GAMING_FAN_BEHAVIOR_METHODID,
			 FAN_BEHAVIOR_CUSTOM);
		FAN_CALL(ACER_WMID_SET_GAMING_FAN_SPEED_METHODID,
			 fan_val_calc(cpu, FAN_INDEX_CPU));
		FAN_CALL(ACER_WMID_SET_GAMING_FAN_SPEED_METHODID,
			 fan_val_calc(gpu, FAN_INDEX_GPU));
	}

	cpu_fan_speed = cpu;
	gpu_fan_speed = gpu;
	pr_info("acer-fan-ctl: fans set to cpu=%d%% gpu=%d%% (0=auto)\n",
		cpu, gpu);
	return 0;
}

static ssize_t fan_speed_show(struct device_driver *driver, char *buf)
{
	return sysfs_emit(buf, "%d,%d\n", cpu_fan_speed, gpu_fan_speed);
}

static ssize_t fan_speed_store(struct device_driver *driver,
			       const char *buf, size_t count)
{
	int cpu, gpu, err;

	if (sscanf(buf, "%d,%d", &cpu, &gpu) != 2)
		return -EINVAL;
	if (cpu < 0 || cpu > 100 || gpu < 0 || gpu > 100)
		return -EINVAL;

	mutex_lock(&fan_lock);
	err = set_fan_speed(cpu, gpu);
	mutex_unlock(&fan_lock);
	if (err)
		return err;

	return count;
}

static DRIVER_ATTR_RW(fan_speed);

static struct attribute *acer_fan_ctl_attrs[] = {
	&driver_attr_fan_speed.attr,
	NULL
};

ATTRIBUTE_GROUPS(acer_fan_ctl);

static const struct wmi_device_id acer_fan_ctl_id_table[] = {
	{ .guid_string = WMID_GUID4 },
	{},
};

static struct wmi_driver acer_fan_ctl_driver = {
	.driver = { .name = "acer-fan-ctl",
		    .groups = acer_fan_ctl_groups },
};

static int __init acer_fan_ctl_init(void)
{
	if (!wmi_has_guid(WMID_GUID4)) {
		pr_err("acer-fan-ctl: Acer gaming WMI interface not found\n");
		return -ENODEV;
	}
	/* No WMI calls here: fans stay exactly as the firmware left them. */
	return wmi_driver_register(&acer_fan_ctl_driver);
}

static void __exit acer_fan_ctl_exit(void)
{
	wmi_driver_unregister(&acer_fan_ctl_driver);
}

module_init(acer_fan_ctl_init);
module_exit(acer_fan_ctl_exit);
