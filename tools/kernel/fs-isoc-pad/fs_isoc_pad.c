// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * fs_isoc_pad: stop the VIA VL805 xHCI (Raspberry Pi 4) from dropping
 * full-speed isochronous IN packets.
 *
 * Behind a transaction translator, when a full-speed isochronous IN packet
 * fills its TRB exactly, the VL805 misses the service opportunity of the next
 * TD (Missed Service Error; -EXDEV with 0 bytes in usbmon). If every buffer is
 * at least one byte longer than the largest packet the device may send, each
 * completion is a short packet and the losses stop
 * (rpi-audio: docs/hw/2026-11-04-pi-usb-host.md).
 *
 * Class drivers size isochronous buffers from wMaxPacketSize, and usbcore
 * refuses longer ones. So, for full-speed devices behind a VL805, this module
 * adds `pad` bytes to wMaxPacketSize of every isochronous IN data endpoint in
 * the host's parsed copy of the descriptors. The raw descriptors that
 * userspace reads stay as the device sent them. It then sets the active
 * configuration again, so the interface drivers bind with the new size.
 * Removing the module puts the original sizes back the same way.
 */
#include <linux/list.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/overflow.h>
#include <linux/pci.h>
#include <linux/slab.h>
#include <linux/usb.h>

#define VL805_VENDOR	0x1106
#define VL805_DEVICE	0x3483

static unsigned int pad = 1;
module_param(pad, uint, 0444);
MODULE_PARM_DESC(pad, "Bytes added to wMaxPacketSize of full-speed isochronous IN endpoints behind a VL805 (default 1, 0 = off)");

struct padded_device {
	struct list_head node;
	struct usb_device *udev;
	unsigned int count;
	struct usb_endpoint_descriptor *eps[] __counted_by(count);
};

static LIST_HEAD(padded_devices);
static DEFINE_MUTEX(padded_lock);

static bool behind_vl805(struct usb_device *udev)
{
	struct device *ctrl = udev->bus->controller;
	struct pci_dev *pdev;

	if (!ctrl || !dev_is_pci(ctrl))
		return false;
	pdev = to_pci_dev(ctrl);
	return pdev->vendor == VL805_VENDOR && pdev->device == VL805_DEVICE;
}

static bool eligible(const struct usb_endpoint_descriptor *d)
{
	unsigned int maxp = usb_endpoint_maxp(d);

	/* Data endpoints only: explicit feedback endpoints carry 3 or 4 bytes. */
	return usb_endpoint_is_isoc_in(d) &&
	       (d->bmAttributes & USB_ENDPOINT_USAGE_MASK) != USB_ENDPOINT_USAGE_FEEDBACK &&
	       maxp && maxp + pad <= 1023;
}

/* Count the eligible endpoints of every configuration; store them when @out is given. */
static unsigned int collect(struct usb_device *udev, struct usb_endpoint_descriptor **out)
{
	unsigned int c, i, a, e, n = 0;

	if (!udev->config)
		return 0;
	for (c = 0; c < udev->descriptor.bNumConfigurations; c++) {
		struct usb_host_config *cfg = &udev->config[c];

		for (i = 0; i < cfg->desc.bNumInterfaces && i < USB_MAXINTERFACES; i++) {
			struct usb_interface_cache *ic = cfg->intf_cache[i];

			for (a = 0; ic && a < ic->num_altsetting; a++) {
				struct usb_host_interface *alt = &ic->altsetting[a];

				for (e = 0; e < alt->desc.bNumEndpoints; e++) {
					struct usb_endpoint_descriptor *d = &alt->endpoint[e].desc;

					if (!eligible(d))
						continue;
					if (out)
						out[n] = d;
					n++;
				}
			}
		}
	}
	return n;
}

static struct padded_device *find_locked(struct usb_device *udev)
{
	struct padded_device *p;

	list_for_each_entry(p, &padded_devices, node)
		if (p->udev == udev)
			return p;
	return NULL;
}

static void reconfigure(struct usb_device *udev)
{
	/* Asynchronous: callers may hold the device lock (notifier) or not (module load). */
	if (udev->actconfig)
		usb_driver_set_configuration(udev, udev->actconfig->desc.bConfigurationValue);
}

static int pad_device(struct usb_device *udev, void *unused)
{
	struct padded_device *p;
	unsigned int n, i;

	if (!pad || udev->speed != USB_SPEED_FULL || !udev->tt || !behind_vl805(udev))
		return 0;
	n = collect(udev, NULL);
	if (!n)
		return 0;

	mutex_lock(&padded_lock);
	if (find_locked(udev))
		goto out;
	p = kzalloc(struct_size(p, eps, n), GFP_KERNEL);
	if (!p)
		goto out;
	p->count = n;
	collect(udev, p->eps);
	for (i = 0; i < n; i++)
		p->eps[i]->wMaxPacketSize = cpu_to_le16(usb_endpoint_maxp(p->eps[i]) + pad);
	p->udev = usb_get_dev(udev);
	list_add(&p->node, &padded_devices);
	dev_info(&udev->dev, "fs_isoc_pad: wMaxPacketSize +%u on %u isochronous IN endpoint(s)\n",
		 pad, n);
	reconfigure(udev);
out:
	mutex_unlock(&padded_lock);
	return 0;
}

static void release(struct padded_device *p, bool restore)
{
	unsigned int i;

	list_del(&p->node);
	if (restore) {
		for (i = 0; i < p->count; i++)
			p->eps[i]->wMaxPacketSize =
				cpu_to_le16(usb_endpoint_maxp(p->eps[i]) - pad);
		reconfigure(p->udev);
	}
	usb_put_dev(p->udev);
	kfree(p);
}

static int notify(struct notifier_block *nb, unsigned long action, void *data)
{
	struct padded_device *p;

	switch (action) {
	case USB_DEVICE_ADD:
		pad_device(data, NULL);
		break;
	case USB_DEVICE_REMOVE:
		mutex_lock(&padded_lock);
		p = find_locked(data);
		if (p)
			release(p, false);
		mutex_unlock(&padded_lock);
		break;
	}
	return NOTIFY_OK;
}

static struct notifier_block fs_isoc_pad_nb = {
	.notifier_call = notify,
};

static int __init fs_isoc_pad_init(void)
{
	usb_register_notify(&fs_isoc_pad_nb);
	usb_for_each_dev(NULL, pad_device);	/* devices that were already there */
	return 0;
}

static void __exit fs_isoc_pad_exit(void)
{
	struct padded_device *p, *tmp;

	usb_unregister_notify(&fs_isoc_pad_nb);
	mutex_lock(&padded_lock);
	list_for_each_entry_safe(p, tmp, &padded_devices, node)
		release(p, true);
	mutex_unlock(&padded_lock);
}

module_init(fs_isoc_pad_init);
module_exit(fs_isoc_pad_exit);

MODULE_DESCRIPTION("Pad wMaxPacketSize of full-speed isochronous IN endpoints behind a VIA VL805");
MODULE_LICENSE("GPL");
