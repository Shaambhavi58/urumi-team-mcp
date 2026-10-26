<?php
// Executed only by the in-cluster bootstrap Job. Secrets come from env, never arguments/logs.
$root = getcwd();
$config = "<?php\ndefine('DB_NAME', 'wordpress');\ndefine('DB_USER', 'wp');\n";
$config .= "define('DB_PASSWORD', " . var_export(getenv('DB_PASSWORD'), true) . ");\n";
$config .= "define('DB_HOST', 'database:3306');\ndefine('DB_CHARSET', 'utf8');\n";
$config .= "define('DISABLE_WP_CRON', true);\ndefine('WP_DEBUG', false);\n";
$config .= '$table_prefix = "wp_";' . "\ndefine('ABSPATH', __DIR__ . '/');\nrequire_once ABSPATH . 'wp-settings.php';\n";
file_put_contents($root . '/wp-config.php', $config);
define('WP_INSTALLING', true);
require $root . '/wp-load.php';
require_once ABSPATH . 'wp-admin/includes/upgrade.php';
require_once ABSPATH . 'wp-admin/includes/plugin.php';
if (!is_blog_installed()) {
    wp_install(getenv('STORE_TITLE'), 'storeadmin', 'admin@example.test', false, '', getenv('ADMIN_PASSWORD'));
}
update_option('home', getenv('STORE_URL'));
update_option('siteurl', getenv('STORE_URL'));
update_option('blogname', getenv('STORE_TITLE'));
update_option('permalink_structure', '');
// The content volume is initialized by the normal WordPress entrypoint before this Job starts.
$result = activate_plugin('woocommerce/woocommerce.php');
if (is_wp_error($result)) { fwrite(STDERR, "WooCommerce activation failed\n"); exit(1); }
// Active plugins are loaded on retries; on first activation load WooCommerce now.
if (!class_exists('WooCommerce')) require_once WP_PLUGIN_DIR . '/woocommerce/woocommerce.php';
if (!did_action('woocommerce_init')) WC()->init();
WC_Install::install();
WC_Install::create_pages();
update_option('show_on_front', 'page');
update_option('page_on_front', wc_get_page_id('shop'));
update_option('timezone_string', 'UTC');
update_option('woocommerce_currency', 'INR');
update_option('woocommerce_default_country', 'IN:HR');
update_option('woocommerce_store_address', 'Demo address');
update_option('woocommerce_store_city', 'Gurugram');
update_option('woocommerce_store_postcode', '122001');
update_option('woocommerce_coming_soon', 'no');
update_option('woocommerce_store_pages_only', 'no');
update_option('woocommerce_cod_settings', ['enabled'=>'yes', 'title'=>'Cash on delivery', 'description'=>'Pay on delivery.', 'instructions'=>'Demo order.', 'enable_for_methods'=>[], 'enable_for_virtual'=>'yes']);
update_option('woocommerce_enable_guest_checkout', 'yes');
$methods = WC_Shipping_Zones::get_zone(0)->get_shipping_methods();
if (!$methods) {
    $zone = new WC_Shipping_Zone(0);
    $instance = $zone->add_shipping_method('free_shipping');
    update_option('woocommerce_free_shipping_' . $instance . '_settings', ['title'=>'Free shipping', 'requires'=>'']);
}
$admin = get_user_by('login', 'storeadmin');
if (!$admin) { fwrite(STDERR, "Store admin missing\n"); exit(1); }
$hashed = wc_api_hash(getenv('WOO_CONSUMER_KEY'));
$table = $wpdb->prefix . 'woocommerce_api_keys';
if (!$wpdb->get_var($wpdb->prepare("SELECT key_id FROM $table WHERE consumer_key = %s", $hashed))) {
    $ok = $wpdb->insert($table, ['user_id'=>$admin->ID, 'description'=>'Urumi provisioner', 'permissions'=>'read_write', 'consumer_key'=>$hashed, 'consumer_secret'=>getenv('WOO_CONSUMER_SECRET'), 'truncated_key'=>substr(getenv('WOO_CONSUMER_KEY'), -7)]);
    if (!$ok) { fwrite(STDERR, "API key initialization failed\n"); exit(1); }
}
echo "Store bootstrap complete\n";
