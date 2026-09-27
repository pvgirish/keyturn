# Synthetic test accounts for the P2a run. No real people or data.
app = Doorkeeper::Application.find_or_create_by!(name: 'p2a-harness') do |a|
  a.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
  a.scopes = 'read write follow'
end
%w(alice bob).each do |u|
  acct = Account.find_local(u) || Account.new(username: u)
  acct.save!(validate: false) unless acct.persisted?
  user = acct.user || User.new(account: acct, email: "#{u}@mastodon.test", password: SecureRandom.hex(16), agreement: true, approved: true, confirmed_at: Time.now.utc, locale: 'en')
  user.save!(validate: false) unless user.persisted?
  t = Doorkeeper::AccessToken.create!(resource_owner_id: user.id, application: app, scopes: 'read write follow')
  puts "#{u.upcase}_TOKEN=#{t.token}"
end
FollowService.new.call(Account.find_local('bob'), Account.find_local('alice'))
puts "bob_follows_alice=#{Account.find_local('bob').following?(Account.find_local('alice'))}"
